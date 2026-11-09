from datetime import date
from decimal import Decimal
import tempfile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from billing.models import Invoice, InvoiceLineItem, Payment, PaymentProof
from operations.models import MaintenanceAttachment, MaintenanceTicket, UserNotification
from properties.models import Lease, Property, Tenant, TenantInvitation, Unit

from .models import Application


class PortalOwnershipTests(TestCase):
    def setUp(self):
        self.media_root = tempfile.TemporaryDirectory()
        self.override = override_settings(MEDIA_ROOT=self.media_root.name)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.addCleanup(self.media_root.cleanup)
        User = get_user_model()
        self.user = User.objects.create_user("resident-one", "one@example.test", "password")
        self.other_user = User.objects.create_user("resident-two", "two@example.test", "password")
        self.tenant = Tenant.objects.create(user=self.user, full_name="Resident One", email=self.user.email, phone="92000001", portal_enabled=True)
        self.other_tenant = Tenant.objects.create(user=self.other_user, full_name="Resident Two", email=self.other_user.email, phone="92000002", portal_enabled=True)
        self.property = Property.objects.create(name="Portal Residence", address="Muscat")
        self.unit = Unit.objects.create(property=self.property, name="101", monthly_rent=Decimal("500.000"), status=Unit.Status.OCCUPIED)
        self.other_unit = Unit.objects.create(property=self.property, name="102", monthly_rent=Decimal("700.000"), status=Unit.Status.OCCUPIED)
        self.lease = self.make_lease(self.tenant, self.unit, "500.000")
        self.other_lease = self.make_lease(self.other_tenant, self.other_unit, "700.000")
        self.invoice = self.make_invoice(self.lease, "PORTAL-INV-1", "500.000")
        self.other_invoice = self.make_invoice(self.other_lease, "PORTAL-INV-2", "700.000")
        self.application = Application.objects.create(
            user=self.user, property=self.property, target_type=Application.TargetType.WHOLE_PROPERTY,
            full_name="Resident One", email=self.user.email, phone="92000001", status=Application.Status.NEW,
            rental_billing_unit="month", rental_billing_interval=1, rental_currency="OMR", rental_amount=Decimal("500.000"),
            open_application_key=f"user:{self.user.pk}|whole_property|{self.property.pk}|property",
        )
        self.other_application = Application.objects.create(
            user=self.other_user, property=self.property, target_type=Application.TargetType.WHOLE_PROPERTY,
            full_name="Resident Two", email=self.other_user.email, phone="92000002", status=Application.Status.NEW,
            rental_billing_unit="month", rental_billing_interval=1, rental_currency="OMR", rental_amount=Decimal("700.000"),
            open_application_key=f"user:{self.other_user.pk}|whole_property|{self.property.pk}|property",
        )
        self.ticket = MaintenanceTicket.objects.create(property=self.property, unit=self.unit, tenant=self.tenant, title="Own ticket", description="Issue", created_by=self.user)
        self.other_ticket = MaintenanceTicket.objects.create(property=self.property, unit=self.other_unit, tenant=self.other_tenant, title="Other ticket", description="Issue", created_by=self.other_user)
        self.notification = UserNotification.objects.create(recipient=self.user, kind="test", title="Own notice", message="Message")
        self.other_notification = UserNotification.objects.create(recipient=self.other_user, kind="test", title="Other notice", message="Message")
        self.client.force_login(self.user)

    def make_lease(self, tenant, unit, rent):
        lease = Lease.objects.create(property=self.property, unit=unit, tenant=tenant, primary_tenant=tenant, start_date=date(2026, 1, 1), end_date=date(2026, 12, 31), monthly_rent=Decimal(rent), rent_amount=Decimal(rent), status=Lease.Status.ACTIVE)
        lease.tenants.add(tenant)
        return lease

    def make_invoice(self, lease, number, amount):
        invoice = Invoice.objects.create(number=number, lease=lease, issue_date=date(2026, 9, 1), due_date=date(2026, 9, 7), currency="OMR", subtotal=Decimal(amount), total=Decimal(amount), status=Invoice.Status.OVERDUE)
        InvoiceLineItem.objects.create(invoice=invoice, description="Rent", quantity=1, unit_price=Decimal(amount), total=Decimal(amount))
        return invoice

    def assert_other_is_hidden(self, name, kwargs, method="get", data=None):
        response = getattr(self.client, method)(reverse(name, kwargs=kwargs), data or {})
        self.assertEqual(response.status_code, 404, name)

    def test_dashboard_supports_tenant_and_applicant_identity(self):
        response = self.client.get(reverse("portal_dashboard"))
        self.assertContains(response, "Welcome, resident-one")
        self.assertContains(response, self.invoice.number)
        self.assertContains(response, self.application.property.name)

    def test_cross_tenant_record_access_is_hidden_for_every_portal_domain(self):
        cases = (
            ("portal_application_detail", {"application_id": self.other_application.pk}),
            ("portal_lease_detail", {"lease_id": self.other_lease.pk}),
            ("portal_invoice_detail", {"invoice_id": self.other_invoice.pk}),
            ("portal_invoice_print", {"invoice_id": self.other_invoice.pk}),
            ("portal_invoice_pdf", {"invoice_id": self.other_invoice.pk}),
            ("portal_maintenance_detail", {"ticket_id": self.other_ticket.pk}),
        )
        for name, kwargs in cases:
            self.assert_other_is_hidden(name, kwargs)
        self.assert_other_is_hidden("portal_application_withdraw", {"application_id": self.other_application.pk}, method="post")
        self.assert_other_is_hidden("portal_payment_submit", {"invoice_id": self.other_invoice.pk}, method="post")
        self.assert_other_is_hidden("portal_gateway_start", {"invoice_id": self.other_invoice.pk}, method="post")
        self.assert_other_is_hidden("portal_notification_read", {"notification_id": self.other_notification.pk}, method="post")

    def test_payment_proof_submission_and_gateway_are_owned(self):
        response = self.client.post(reverse("portal_payment_submit", kwargs={"invoice_id": self.invoice.pk}), {
            "amount": "125.000", "method": Payment.Method.BANK_TRANSFER, "payment_date": "2026-09-29",
            "notes": "First installment", "proof": SimpleUploadedFile("receipt.pdf", b"receipt", content_type="application/pdf"),
        })
        self.assertRedirects(response, reverse("portal_invoice_detail", kwargs={"invoice_id": self.invoice.pk}))
        payment = Payment.objects.get(invoice=self.invoice)
        self.assertEqual(payment.status, Payment.Status.PENDING)
        proof = payment.proofs.get()
        response = self.client.get(reverse("portal_payment_proof", kwargs={"proof_id": proof.pk}))
        try:
            self.assertEqual(response.status_code, 200)
            self.assertEqual(b"".join(response.streaming_content), b"receipt")
        finally:
            if not response.closed:
                response.close()
        self.assertTrue(response.closed)
        self.client.post(reverse("portal_gateway_start", kwargs={"invoice_id": self.invoice.pk}), {"gateway": "manual"})
        self.assertEqual(self.invoice.payment_attempts.count(), 1)

    def test_other_payment_proof_and_maintenance_attachment_are_hidden(self):
        payment = Payment.objects.create(reference="OTHER-PAY", invoice=self.other_invoice, tenant=self.other_tenant, amount=Decimal("10.000"), currency="OMR", status=Payment.Status.PENDING)
        proof = PaymentProof.objects.create(payment=payment, file=SimpleUploadedFile("other.pdf", b"other"), original_name="other.pdf")
        attachment = MaintenanceAttachment.objects.create(ticket=self.other_ticket, file=SimpleUploadedFile("other.pdf", b"other"), original_name="other.pdf")
        self.assert_other_is_hidden("portal_payment_proof", {"proof_id": proof.pk})
        self.assert_other_is_hidden("portal_maintenance_attachment", {"attachment_id": attachment.pk})

    def test_maintenance_creation_restricts_lease_choices(self):
        response = self.client.post(reverse("portal_maintenance_create"), {
            "lease": self.other_lease.pk, "title": "Crafted", "description": "Should fail", "priority": "medium",
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(MaintenanceTicket.objects.filter(title="Crafted").exists())
        response = self.client.post(reverse("portal_maintenance_create"), {
            "lease": self.lease.pk, "location": "Kitchen", "title": "Water leak", "description": "Under sink", "priority": "urgent",
        })
        ticket = MaintenanceTicket.objects.get(title="Water leak")
        self.assertRedirects(response, reverse("portal_maintenance_detail", kwargs={"ticket_id": ticket.pk}))
        self.assertEqual(ticket.tenant, self.tenant)

    def test_application_withdraw_and_notifications_are_owned(self):
        self.client.post(reverse("portal_application_withdraw", kwargs={"application_id": self.application.pk}))
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, Application.Status.WITHDRAWN)
        self.client.post(reverse("portal_notification_read", kwargs={"notification_id": self.notification.pk}))
        self.notification.refresh_from_db()
        self.assertIsNotNone(self.notification.read_at)

    def test_invoice_print_pdf_and_profile(self):
        self.assertEqual(self.client.get(reverse("portal_invoice_print", kwargs={"invoice_id": self.invoice.pk})).status_code, 200)
        response = self.client.get(reverse("portal_invoice_pdf", kwargs={"invoice_id": self.invoice.pk}))
        try:
            self.assertEqual(response.status_code, 200)
            self.assertTrue(b"".join(response.streaming_content).startswith(b"%PDF-"))
        finally:
            if not response.closed:
                response.close()
        self.assertTrue(response.closed)
        response = self.client.post(reverse("portal_profile"), {"first_name": "Updated", "last_name": "Resident", "email": "updated@example.test", "phone": "92009999", "preferred_language": "en", "timezone": "Asia/Muscat"})
        self.assertRedirects(response, reverse("portal_profile"))
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "Updated")


class TenantInvitationPortalTests(TestCase):
    def test_invitation_acceptance_signs_in_and_opens_portal(self):
        tenant = Tenant.objects.create(full_name="Invited Tenant", email="invite@example.test", phone="92000003")
        invitation, token = TenantInvitation.issue(tenant, tenant.email)
        response = self.client.post(reverse("tenant_invitation_accept", kwargs={"token": token}), {
            "new_password1": "A-long-safe-demo-password-2060!",
            "new_password2": "A-long-safe-demo-password-2060!",
        })
        self.assertRedirects(response, reverse("portal_dashboard"))
        tenant.refresh_from_db()
        invitation.refresh_from_db()
        self.assertTrue(tenant.portal_enabled)
        self.assertIsNotNone(invitation.accepted_at)
        self.assertEqual(int(self.client.session["_auth_user_id"]), tenant.user_id)
