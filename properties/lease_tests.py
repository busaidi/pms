from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from billing.models import Invoice
from .forms import TenantDocumentForm
from .lease_services import create_lease, generate_rent_schedule, move_lease, move_out_lease, renew_lease
from .models import DepositSettlement, Lease, LeaseNotificationEvent, Property, PropertyRate, PropertyType, RentSchedule, Tenant, TenantInvitation, Unit, UnitRate, UnitType, UnitTypeRate
from .transfers import validate_rows


class LeaseLifecycleTests(TestCase):
    def setUp(self):
        kind = PropertyType.objects.create(name="Apartment", slug="apartment")
        self.property = Property.objects.create(name="Lease House", slug="lease-house", property_type=kind, rental_mode="hybrid", address="Muscat")
        self.unit_type = UnitType.objects.create(property=self.property, name="Studio", public_slug="studio")
        self.unit = Unit.objects.create(property=self.property, unit_type=self.unit_type, name="101", monthly_rent="300", capacity=2)
        self.other = Unit.objects.create(property=self.property, unit_type=self.unit_type, name="102", monthly_rent="320", capacity=2)
        self.tenant = Tenant.objects.create(full_name="Primary Tenant", phone="90000001")
        self.second = Tenant.objects.create(full_name="Second Tenant", phone="90000002")
        UnitTypeRate.objects.create(unit_type=self.unit_type, amount="300", starts_on=date(2026, 1, 1))
        PropertyRate.objects.create(property=self.property, amount="2000", starts_on=date(2026, 1, 1))

    def create_unit_lease(self, **overrides):
        values = {"property_obj": self.property, "unit": self.unit, "tenants": [self.tenant], "start_date": date(2026, 9, 1), "end_date": date(2027, 8, 31), "deposit_amount": "300"}
        values.update(overrides)
        return create_lease(**values)

    def test_create_unit_lease_snapshots_inherited_rate_and_schedule(self):
        lease = self.create_unit_lease(tenants=[self.tenant, self.second])
        self.assertEqual(lease.unit_type_rate.amount, Decimal("300")); self.assertEqual(lease.currency, "OMR")
        self.assertEqual(lease.tenants.count(), 2); self.assertEqual(lease.rent_schedule.count(), 12)
        self.assertEqual(lease.notification_events.get().scheduled_for, date(2027, 8, 1))
        self.unit.refresh_from_db(); self.assertEqual(self.unit.status, Unit.Status.OCCUPIED)

    def test_schedule_refresh_preserves_invoiced_period_and_reschedules_expiration(self):
        lease = self.create_unit_lease()
        first = lease.rent_schedule.first(); first.status = RentSchedule.Status.INVOICED; first.save(update_fields=("status",))
        lease.rent_amount = Decimal("350"); lease.end_date = date(2027, 9, 30); lease.save()
        generate_rent_schedule(lease)
        first.refresh_from_db()
        self.assertEqual(first.amount, Decimal("300")); self.assertEqual(first.status, RentSchedule.Status.INVOICED)
        self.assertFalse(lease.rent_schedule.filter(status=RentSchedule.Status.SCHEDULED).exclude(amount=Decimal("350")).exists())
        self.assertEqual(lease.notification_events.get().scheduled_for, date(2027, 8, 31))

    def test_unit_rate_overrides_type_rate_for_lease(self):
        rate = UnitRate.objects.create(unit=self.unit, amount="275", starts_on=date(2026, 1, 1))
        lease = self.create_unit_lease()
        self.assertEqual(lease.unit_rate, rate); self.assertEqual(lease.rent_amount, Decimal("275"))

    def test_whole_property_conflicts_with_active_unit_lease(self):
        self.create_unit_lease()
        with self.assertRaisesMessage(ValidationError, "already has an active lease"):
            create_lease(property_obj=self.property, tenants=[self.second], start_date=date(2026, 9, 1))

    def test_unit_type_target_selects_next_available_unit(self):
        lease = create_lease(property_obj=self.property, unit_type=self.unit_type, tenants=[self.tenant], start_date=date(2026, 9, 1), end_date=date(2026, 12, 31))
        self.assertEqual(lease.unit, self.unit)

    def test_capacity_is_enforced(self):
        third = Tenant.objects.create(full_name="Third", phone="90000003")
        with self.assertRaisesMessage(ValidationError, "capacity"):
            self.create_unit_lease(tenants=[self.tenant, self.second, third])

    def test_move_records_lineage_and_updates_status(self):
        lease = self.create_unit_lease(); move_lease(lease, target_unit=self.other, effective_date=date(2026, 10, 1), reason="Upgrade", handover_confirmed=True)
        lease.refresh_from_db(); self.unit.refresh_from_db(); self.other.refresh_from_db()
        self.assertEqual(lease.unit, self.other); self.assertEqual(self.unit.status, Unit.Status.AVAILABLE); self.assertEqual(self.other.status, Unit.Status.OCCUPIED)
        self.assertEqual(lease.unit_history.get().from_unit, self.unit)

    def test_renewal_requires_outstanding_confirmation_and_links_chain(self):
        lease = self.create_unit_lease()
        Invoice.objects.create(number="INV-OUTSTANDING", lease=lease, issue_date=date.today(), due_date=date.today(), total="50", subtotal="50", status="overdue")
        with self.assertRaisesMessage(ValidationError, "outstanding balance"):
            renew_lease(lease, end_date=date(2028, 8, 31), rent_amount="325")
        renewed = renew_lease(lease, end_date=date(2028, 8, 31), rent_amount="325", confirmed_outstanding=True)
        lease.refresh_from_db(); self.assertEqual(lease.status, Lease.Status.RENEWED); self.assertEqual(renewed.previous_lease, lease)

    def test_move_out_and_deposit_settlement_are_atomic(self):
        lease = self.create_unit_lease()
        move_out_lease(lease, end_date=date(2026, 10, 1), reason="Leaving", handover_confirmed=True, settlement={"refund_amount": Decimal("250"), "deductions": [("Cleaning", Decimal("50"))], "status": "settled"})
        lease.refresh_from_db(); self.assertEqual(lease.status, Lease.Status.TERMINATED)
        self.assertEqual(lease.deposit_settlement.status, DepositSettlement.Status.SETTLED); self.assertEqual(lease.deposit_settlement.deductions.get().amount, Decimal("50"))

    def test_tenant_with_active_lease_cannot_be_archived(self):
        self.create_unit_lease()
        with self.assertRaisesMessage(ValidationError, "active lease"): self.tenant.archive()

    def test_tenant_csv_is_transactional(self):
        base = {"phone": "90000111", "email": "", "id_number": "", "nationality": "", "emergency_contact_name": "", "emergency_contact_phone": "", "notes": "", "is_active": "1"}
        rows = [{**base, "full_name": "Imported"}, {**base, "full_name": "Imported"}]
        _, errors = validate_rows("tenants", rows, None, persist=True)
        self.assertTrue(errors); self.assertFalse(Tenant.objects.filter(full_name="Imported").exists())

    def test_tenant_invitation_sets_password_and_links_user(self):
        superseded, _created = TenantInvitation.issue(self.tenant, "old@example.test")
        invitation, raw = TenantInvitation.issue(self.tenant, "tenant@example.test")
        superseded.refresh_from_db(); self.assertFalse(superseded.is_usable)
        response = self.client.post(f"/tenant-invite/{raw}/", {"new_password1": "Strong-pass-123!", "new_password2": "Strong-pass-123!"})
        self.assertRedirects(response, "/portal/")
        self.tenant.refresh_from_db(); invitation.refresh_from_db()
        self.assertTrue(self.tenant.portal_enabled); self.assertIsNotNone(self.tenant.user_id); self.assertIsNotNone(invitation.accepted_at)
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.tenant.user_id)

    def test_tenant_document_rejects_unsupported_or_oversized_files(self):
        bad_type = TenantDocumentForm(data={"name": "Script", "document_type": "other"}, files={"file": SimpleUploadedFile("script.exe", b"x")})
        self.assertFalse(bad_type.is_valid()); self.assertIn("file", bad_type.errors)
        oversized = TenantDocumentForm(data={"name": "Large", "document_type": "other"}, files={"file": SimpleUploadedFile("large.pdf", b"x" * (10 * 1024 * 1024 + 1), content_type="application/pdf")})
        self.assertFalse(oversized.is_valid()); self.assertIn("file", oversized.errors)
