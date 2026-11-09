from datetime import date
from decimal import Decimal
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.base import ContentFile
from django.conf import settings
from django.test import TestCase
from django.urls import reverse

from accounts.models import Capability, GroupProfile, PropertyAccess
from .contract_services import ensure_contract, render_contract
from .lease_services import create_lease
from .models import LeaseContractProfile, Property, RentSchedule, Tenant, Unit


class LeaseContractTests(TestCase):
    def test_unsaved_terms_preview_uses_draft_without_writing_contracts_or_templates(self):
        from .models import ContractTermsTemplate, LeaseContract
        from .contract_terms import default_terms
        template = default_terms(self.property)
        before = (ContractTermsTemplate.objects.count(), LeaseContract.objects.count())
        self.client.force_login(self.admin)
        response = self.client.post(reverse("terms_template_preview", args=(self.property.pk,)), {
            "name": "مسودة معاينة", "body": '<h3>عنوان غير محفوظ</h3><p>شرط جديد <strong>مهم</strong></p><script>alert(1)</script>',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "عنوان غير محفوظ")
        self.assertContains(response, "معاينة غير معتمدة")
        self.assertContains(response, 'class="page dynamic cover"')
        self.assertContains(response, "Contract Tajawal")
        self.assertNotContains(response, "alert(1)")
        self.assertNotContains(response, self.tenant.full_name)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertIn("script-src 'sha256-", response["Content-Security-Policy"])
        template.refresh_from_db()
        self.assertNotIn("عنوان غير محفوظ", template.body)
        self.assertEqual(before, (ContractTermsTemplate.objects.count(), LeaseContract.objects.count()))

    def test_terms_preview_requires_post_permission_and_nonempty_content(self):
        url = reverse("terms_template_preview", args=(self.property.pk,))
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertEqual(self.client.post(url, {"body": "<p><br></p>"}).status_code, 400)
        viewer = get_user_model().objects.create_user("preview-limited")
        self.client.force_login(viewer)
        self.assertEqual(self.client.post(url, {"body": "<p>Test</p>"}).status_code, 404)

    def setUp(self):
        self.property = Property.objects.create(name="Test Residence", address="Muscat")
        self.unit = Unit.objects.create(property=self.property, name="24", monthly_rent="45", capacity=4)
        self.tenant = Tenant.objects.create(full_name="نزيل اختبار", phone="90000000", id_number="TEST-ID")
        self.admin = get_user_model().objects.create_superuser("contract-admin", "admin@example.test", "test-password")
        LeaseContractProfile.objects.create(property=self.property, lessor_name="مؤجر اختبار")

    def lease(self):
        return create_lease(property_obj=self.property, unit=self.unit, tenants=[self.tenant],
                            start_date=date(2026, 10, 26), end_date=date(2026, 10, 26),
                            rent_amount="45", billing_unit="day", billing_interval=1, deposit_amount="20")

    def test_registration_creates_snapshot_with_exclusive_departure(self):
        lease = self.lease()
        contract = lease.contracts.get()
        self.assertEqual(contract.snapshot["checkout"], "27/10/2026")
        self.assertEqual(contract.snapshot["nights"], 1)
        self.assertEqual(contract.snapshot["total"], "45.000")
        self.assertEqual(contract.snapshot["deposit"], "20.000")

    def test_lessor_signature_is_versioned_and_tenant_signature_stays_blank(self):
        lease = self.lease()
        unsigned = lease.contracts.get()
        profile = self.property.contract_profile
        profile.lessor_signature.save("test-signature.png", ContentFile(b"test-signature-image"))
        self.addCleanup(profile.lessor_signature.delete, save=False)
        signed = ensure_contract(lease)
        self.assertEqual(signed.revision, 2)
        self.assertTrue(signed.snapshot["lessor_signature"].startswith("data:image/png;base64,"))
        unsigned.refresh_from_db()
        self.assertEqual(unsigned.snapshot["lessor_signature"], "")
        html = render_contract(signed)
        lessor = html.split('class="signature lessor-signature"')[1].split('class="signature tenant-signature"')[0]
        tenant = html.split('class="signature tenant-signature"')[1].split('</div>')[0]
        self.assertIn('<img ', lessor)
        self.assertNotIn('<img ', tenant)
        self.assertIn("__________________", tenant)
        profile.lessor_signature.delete()
        self.assertEqual(ensure_contract(lease).revision, 3)
        self.assertIn('<img ', render_contract(signed).split('class="signature lessor-signature"')[1].split('class="signature tenant-signature"')[0])

    def test_existing_exclusive_end_uses_actual_schedule(self):
        lease = self.lease()
        lease.end_date = date(2026, 10, 27)
        lease.save()
        self.assertEqual(ensure_contract(lease).snapshot["checkout"], "27/10/2026")

    def test_unchanged_snapshot_reused_and_old_version_preserved(self):
        lease = self.lease()
        first = lease.contracts.get()
        self.assertEqual(ensure_contract(lease).pk, first.pk)
        self.tenant.full_name = "اسم جديد"
        self.tenant.save()
        second = ensure_contract(lease)
        self.assertEqual(second.revision, 2)
        first.refresh_from_db()
        self.assertEqual(first.snapshot["tenants"][0]["name"], "نزيل اختبار")
        self.assertEqual(second.snapshot["tenants"][0]["name"], "اسم جديد")

    def test_all_tenants_and_schedule_total_are_used(self):
        lease = self.lease()
        second = Tenant.objects.create(full_name="Second tenant", phone="90000001")
        lease.tenants.add(second)
        RentSchedule.objects.create(lease=lease, due_date=date(2026, 10, 27), period_start=date(2026, 10, 27), period_end=date(2026, 10, 27), amount=Decimal("35.125"))
        contract = ensure_contract(lease)
        self.assertEqual(len(contract.snapshot["tenants"]), 2)
        self.assertEqual(contract.snapshot["total"], "80.125")

    def test_private_notes_and_source_identity_are_not_in_output(self):
        lease = self.lease()
        lease.notes = "PRIVATE-ADMIN-NOTE"
        lease.save()
        html = render_contract(ensure_contract(lease))
        self.assertIn("نزيل اختبار", html)
        for forbidden in ("PRIVATE-ADMIN-NOTE", "SKY00639", "جواهر", "11537916"):
            self.assertNotIn(forbidden, html)
        self.assertIn("التوقيع: __________________", html)

    def test_html_escapes_tenant_data(self):
        self.tenant.full_name = '<script>alert("x")</script>'
        self.tenant.save()
        html = render_contract(self.lease().contracts.get())
        self.assertNotIn('<script>alert', html)
        self.assertIn("&lt;script&gt;", html)

    def test_property_scoped_access_protects_preview_download_and_generation(self):
        lease = self.lease()
        contract = lease.contracts.get()
        user = get_user_model().objects.create_user("limited")
        group = Group.objects.create(name="Lease viewer")
        GroupProfile.objects.create(group=group)
        Capability.objects.create(name="leases.view").groups.add(group)
        other = Property.objects.create(name="Other", address="Other address")
        access = PropertyAccess.objects.create(user=user, property=other, group=group)
        self.client.force_login(user)
        for name in ("contract_preview", "contract_download"):
            self.assertEqual(self.client.get(reverse(name, args=(lease.pk, contract.pk))).status_code, 404)
        self.assertEqual(self.client.post(reverse("contract_generate", args=(lease.pk,))).status_code, 404)
        access.property = self.property
        access.save()
        response = self.client.get(reverse("contract_preview", args=(lease.pk, contract.pk)))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertEqual(self.client.post(reverse("contract_generate", args=(lease.pk,))).status_code, 404)

    def test_profile_change_does_not_rewrite_previous_snapshot(self):
        lease = self.lease()
        contract = lease.contracts.get()
        profile = self.property.contract_profile
        profile.lessor_name = "مؤجر آخر"
        profile.save()
        self.assertEqual(contract.snapshot["profile"]["lessor_name"], "مؤجر اختبار")
        self.assertEqual(ensure_contract(lease).revision, 2)

    @patch("properties.contract_views.ensure_contract_pdf", side_effect=OSError("renderer unavailable"))
    def test_renderer_failure_keeps_contract_and_supports_retry(self, renderer):
        lease = self.lease()
        self.client.force_login(self.admin)
        response = self.client.post(reverse("contract_generate", args=(lease.pk,)))
        self.assertRedirects(response, reverse("lease_workspace", args=(lease.pk,)))
        self.assertEqual(lease.contracts.count(), 1)

    def test_open_ended_contract_is_flagged(self):
        lease = self.lease()
        lease.end_date = None
        lease.save()
        self.assertTrue(ensure_contract(lease).snapshot["warnings"])
        self.assertIsNone(ensure_contract(lease).snapshot["nights"])
        self.assertEqual(ensure_contract(lease).snapshot["total"], "")

    def test_terms_have_no_template_variables_and_are_identical_across_contracts(self):
        source = (Path(settings.BASE_DIR) / "templates/properties/contracts/terms_v6.html").read_text(encoding="utf-8")
        self.assertNotIn("{{", source)
        self.assertNotIn("{%", source)
        contract = self.lease().contracts.get()
        contract.template_version = "atheer-v8"  # Historical static documents remain unchanged.
        original = render_contract(contract)
        changed = deepcopy(contract)
        changed.snapshot["reference"] = "OTHER-REFERENCE"
        changed.snapshot["start"] = "15/05/2030"
        changed.snapshot["checkout"] = "20/05/2030"
        changed.snapshot["unit"] = "99"
        changed.snapshot["total"] = "1234.567"
        changed.snapshot["deposit"] = "111.222"
        changed.snapshot["tenants"][0]["name"] = "Different tenant"
        updated = render_contract(changed)
        def terms(html):
            return html.split("<!-- FIXED_TERMS_START -->")[1].split("<!-- FIXED_TERMS_END -->")[0]
        self.assertEqual(terms(original), terms(updated))
        self.assertEqual(terms(original).count('class="page dynamic terms-page"'), 4)
        self.assertIn("1234.567", updated)
        self.assertNotIn("1234.567", terms(updated))

    def test_reformatted_terms_preserve_all_approved_text(self):
        import re
        directory = Path(settings.BASE_DIR) / "templates/properties/contracts"
        previous = (directory / "terms_v3.html").read_text(encoding="utf-8")
        current = (directory / "terms_v6.html").read_text(encoding="utf-8")
        pattern = r'<h3>.*?</h3>|<p(?: class="small")?>.*?</p>'
        self.assertEqual(re.findall(pattern, previous, re.S), re.findall(pattern, current, re.S))

    def test_previous_template_remains_renderable_and_is_not_rewritten(self):
        from .models import LeaseContract
        lease = self.lease()
        initial = lease.contracts.get()
        LeaseContract.objects.filter(pk=initial.pk).update(template_version="atheer-short-v1", fingerprint="old-template")
        initial.refresh_from_db()
        old_html = render_contract(initial)
        self.assertNotIn("<!-- FIXED_TERMS_START -->", old_html)
        updated = ensure_contract(lease)
        self.assertEqual(updated.template_version, "atheer-v9")
        self.assertEqual(updated.revision, 2)
        initial.refresh_from_db()
        self.assertEqual(render_contract(initial), old_html)

    def test_selected_terms_are_snapshotted_and_old_html_is_immutable(self):
        from .models import ContractTermsTemplate
        lease = self.lease()
        template = ContractTermsTemplate.objects.create(property=self.property, name="Custom", body="<h3>Custom heading</h3><p>Original clause</p>")
        lease.terms_template = template
        lease.save()
        first = ensure_contract(lease)
        old_html = render_contract(first)
        template.body = "<p>Updated clause</p>"
        template.revision += 1
        template.save()
        second = ensure_contract(lease)
        self.assertEqual(second.snapshot["selected_terms"]["html"], template.body)
        self.assertNotEqual(first.pk, second.pk)
        first.refresh_from_db()
        self.assertEqual(render_contract(first), old_html)
        self.assertIn("Original clause", old_html)

    def test_terms_sanitization_removes_active_content_without_interpolating_variables(self):
        from .contract_terms import clean_terms
        value = clean_terms('<p onclick="bad()">{{ data.total }} <strong>Keep</strong></p><script>alert(1)</script><img src="https://example.com/x"><iframe>bad</iframe>')
        self.assertEqual(value, '<p>{{ data.total }} <strong>Keep</strong></p>')
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            clean_terms("<p><br></p>")

    @patch("properties.contract_views.ensure_contract_pdf")
    def test_selection_rejects_foreign_or_disabled_template(self, renderer):
        from .models import ContractTermsTemplate
        lease = self.lease()
        other = Property.objects.create(name="Other", address="Muscat")
        template = ContractTermsTemplate.objects.create(property=other, name="Other terms", body="<p>Private terms</p>")
        self.client.force_login(self.admin)
        original = lease.terms_template_id
        url = reverse("contract_generate", args=(lease.pk,))
        self.client.post(url, {"terms_template": template.pk})
        lease.refresh_from_db()
        self.assertEqual(lease.terms_template_id, original)
        template.property = self.property
        template.is_active = False
        template.save()
        self.client.post(url, {"terms_template": template.pk})
        lease.refresh_from_db()
        self.assertEqual(lease.terms_template_id, original)
        renderer.assert_not_called()

    def test_editor_saves_and_rejects_stale_updates(self):
        from .contract_terms import default_terms
        template = default_terms(self.property)
        self.client.force_login(self.admin)
        url = reverse("terms_template_edit", args=(self.property.pk, template.pk))
        data = {"name": "Edited", "body": "<h3>Terms</h3><p>New text</p>", "expected_revision": template.revision, "is_active": "on"}
        self.assertEqual(self.client.post(url, data).status_code, 302)
        template.refresh_from_db()
        self.assertEqual(template.revision, 2)
        data["body"] = "<p>Stale overwrite</p>"
        self.assertEqual(self.client.post(url, data).status_code, 200)
        template.refresh_from_db()
        self.assertNotIn("Stale", template.body)
        self.assertEqual(self.client.post(url, {**data, "expected_revision": 2, "body": "<p><br></p>"}).status_code, 200)

    def test_terms_editor_requires_property_management_access(self):
        from .contract_terms import default_terms
        template = default_terms(self.property)
        user = get_user_model().objects.create_user("terms-viewer")
        self.client.force_login(user)
        url = reverse("terms_template_edit", args=(self.property.pk, template.pk))
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.post(url, {"body": "<p>Changed</p>"}).status_code, 404)

    @patch("properties.contract_views.ensure_contract_pdf")
    def test_valid_template_selection_generates_selected_snapshot(self, renderer):
        from .models import ContractTermsTemplate
        lease = self.lease()
        template = ContractTermsTemplate.objects.create(property=self.property, name="Selected", body="<p>Selected content</p>")
        self.client.force_login(self.admin)
        response = self.client.post(reverse("contract_generate", args=(lease.pk,)), {"terms_template": template.pk})
        self.assertEqual(response.status_code, 302)
        lease.refresh_from_db()
        self.assertEqual(lease.terms_template_id, template.pk)
        self.assertEqual(lease.contracts.first().snapshot["selected_terms"]["html"], template.body)
        renderer.assert_called_once()

    def test_creation_form_rejects_template_for_another_accessible_property(self):
        from .forms import LeaseCreateForm
        from .models import ContractTermsTemplate
        other = Property.objects.create(name="Other accessible", address="Muscat")
        template = ContractTermsTemplate.objects.create(property=other, name="Other", body="<p>Other</p>")
        form = LeaseCreateForm({"property": self.property.pk, "target_type": "unit", "unit": self.unit.pk,
            "tenants": [self.tenant.pk], "start_date": "2026-10-26", "end_date": "2026-10-26", "rent_amount": "45",
            "billing_strategy": "advance", "billing_day": "1", "deposit_amount": "0", "terms_template": template.pk},
            properties=Property.objects.all(), tenants=Tenant.objects.all())
        self.assertFalse(form.is_valid())
        self.assertIn("terms_template", form.errors)
