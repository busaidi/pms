import base64
import copy
import io
import json
import tempfile
import hashlib
from datetime import date
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from django.contrib.auth import get_user_model
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from accounts.models import AuditLog
from billing.models import Invoice
from .contract_transfer import export_bundle, plan_import, apply_bundle
from .models import Property, ContractTermsTemplate, LeaseContractProfile, Tenant, Lease


class ContractTransferTests(TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.enterContext(override_settings(LEASE_CONTRACT_ROOT=self.directory.name))
        self.actor = get_user_model().objects.create_superuser("deployer", "deploy@example.test", "test")
        self.prop = Property.objects.create(name="Transfer House", slug="transfer-house", address="Muscat")
        self.profile = LeaseContractProfile.objects.create(property=self.prop, lessor_name="Owner")
        content = io.BytesIO()
        Image.new("RGB", (5, 5), "white").save(content, format="PNG")
        self.signature = content.getvalue()
        self.profile.lessor_signature.save("signature.png", ContentFile(self.signature))
        self.term = ContractTermsTemplate.objects.create(property=self.prop, name="Approved", body="<p>Terms</p>", is_default=True)
        self.bundle = export_bundle(Property.objects.filter(pk=self.prop.pk))

    def clear_config(self):
        self.term.delete()
        self.profile.lessor_signature.delete(save=False)
        self.profile.delete()

    def write_bundle(self):
        path = Path(self.directory.name) / "test.contract-bundle.json"
        path.write_text(json.dumps(self.bundle), encoding="utf8")
        return path

    def test_export_excludes_operational_records_and_paths(self):
        row = self.bundle["properties"][0]
        self.assertEqual(set(row), {"property", "profile", "signature", "terms"})
        self.assertEqual(set(row["property"]), {"slug", "name"})
        self.assertEqual(base64.b64decode(row["signature"]), self.signature)

    def test_preview_does_not_write_and_apply_is_idempotent_and_audited(self):
        self.clear_config()
        path = self.write_bundle()
        before_files = list(Path(self.directory.name).rglob("*"))
        call_command("import_contract_config", str(path), stdout=io.StringIO())
        self.assertFalse(LeaseContractProfile.objects.exists())
        self.assertFalse(ContractTermsTemplate.objects.exists())
        self.assertEqual(list(Path(self.directory.name).rglob("*")), before_files)
        apply_bundle(self.bundle, self.actor)
        profile = LeaseContractProfile.objects.get()
        with profile.lessor_signature.open("rb") as stream:
            self.assertEqual(stream.read(), self.signature)
        audit_count = AuditLog.objects.count()
        self.assertGreater(audit_count, 0)
        apply_bundle(self.bundle, self.actor)
        self.assertEqual(AuditLog.objects.count(), audit_count)
        self.assertEqual(ContractTermsTemplate.objects.count(), 1)
        self.assertFalse(Lease.objects.exists())
        self.assertFalse(Tenant.objects.exists())

    def test_conflict_prevents_all_changes(self):
        self.bundle["properties"][0]["profile"]["lessor_name"] = "Changed"
        with self.assertRaisesRegex(ValueError, "conflict"):
            apply_bundle(self.bundle, self.actor)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.lessor_name, "Owner")
        self.assertFalse(AuditLog.objects.exists())

    def test_property_identity_must_match_not_just_primary_key(self):
        self.bundle["properties"][0]["property"]["name"] = "Other house"
        with self.assertRaises(Property.DoesNotExist):
            plan_import(self.bundle)

    def test_apply_requires_checksum_database_and_actor(self):
        path = self.write_bundle()
        with self.assertRaises(CommandError):
            call_command("import_contract_config", str(path), apply=True, stdout=io.StringIO())
        with self.assertRaisesRegex(CommandError, "checksum"):
            call_command("import_contract_config", str(path), sha256="wrong", stdout=io.StringIO())

    def test_rollback_removes_new_signature_file(self):
        self.clear_config()
        before = list(Path(self.directory.name).rglob("*.png"))
        with patch.object(ContractTermsTemplate.objects, "create", side_effect=RuntimeError("failure")):
            with self.assertRaises(RuntimeError):
                apply_bundle(self.bundle, self.actor)
        self.assertEqual(list(Path(self.directory.name).rglob("*.png")), before)
        self.assertFalse(LeaseContractProfile.objects.exists())
        self.assertFalse(AuditLog.objects.exists())

    def test_invalid_signature_and_unsafe_terms_rejected(self):
        invalid = copy.deepcopy(self.bundle)
        invalid["properties"][0]["signature"] = base64.b64encode(b"not an image").decode()
        with self.assertRaises(OSError):
            plan_import(invalid)
        self.bundle["properties"][0]["terms"][0]["body"] = '<p onclick="evil()">Terms</p>'
        with self.assertRaisesRegex(ValueError, "unsupported HTML"):
            plan_import(self.bundle)

    def test_existing_default_or_same_name_different_content_not_replaced(self):
        self.bundle["properties"][0]["terms"][0]["name"] = "Different default"
        with self.assertRaisesRegex(ValueError, "Default terms already"):
            plan_import(self.bundle)
        self.bundle["properties"][0]["terms"][0]["name"] = self.term.name
        self.bundle["properties"][0]["terms"][0]["body"] = "<p>Changed</p>"
        with self.assertRaisesRegex(ValueError, "Terms conflict"):
            plan_import(self.bundle)

    def test_export_refuses_overwriting_existing_bundle(self):
        path = self.write_bundle()
        original = path.read_bytes()
        with self.assertRaises(CommandError):
            call_command("export_contract_config", str(path), stdout=io.StringIO())
        self.assertEqual(path.read_bytes(), original)

    def test_command_import_preserves_existing_operational_data(self):
        tenant = Tenant.objects.create(full_name="Existing resident", phone="90000000")
        lease = Lease.objects.create(property=self.prop, tenant=tenant, start_date=date(2026, 1, 1), monthly_rent="300", status="active")
        Invoice.objects.create(number="EXISTING-INVOICE", lease=lease, issue_date=date(2026, 1, 1), due_date=date(2026, 1, 5), total="300", subtotal="300", status="overdue")
        models = (Property, Tenant, Lease, Invoice)
        before = {model: list(model.objects.order_by("pk").values()) for model in models}
        self.clear_config()
        path = self.write_bundle()
        call_command("import_contract_config", str(path), apply=True,
                     sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                     database_name=settings.DATABASES["default"]["NAME"], actor=self.actor.username,
                     stdout=io.StringIO())
        for model in models:
            self.assertEqual(list(model.objects.order_by("pk").values()), before[model])
        self.assertEqual(ContractTermsTemplate.objects.count(), 1)
        self.assertEqual(LeaseContractProfile.objects.count(), 1)
