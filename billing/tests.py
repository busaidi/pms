import tempfile
import json
from unittest.mock import patch
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core import signing
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from properties.lease_services import generate_rent_schedule
from properties.models import Lease, Property, Tenant, Unit

from .forms import PaymentForm
from .gateways import apply_gateway_result, process_webhook, start_payment_attempt
from .models import Invoice, InvoicePdfArtifact, Payment, PaymentAnomaly, PaymentAttempt
from .services import complete_payment, create_manual_invoice, ensure_invoice_pdf, generate_invoices, invoice_from_signed_token, record_payment, signed_invoice_token, verify_payment, void_invoice


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="pms-billing-tests-"))
class BillingLifecycleTests(TestCase):
    def setUp(self):
        self.actor = get_user_model().objects.create_superuser(username="billing-admin", email="billing@example.test", password="test-pass")
        self.property = Property.objects.create(name="Billing House", slug="billing-house", address="Muscat")
        self.unit = Unit.objects.create(property=self.property, name="101", monthly_rent="500", status=Unit.Status.OCCUPIED)
        self.tenant = Tenant.objects.create(full_name="Billing Tenant", phone="90000000")
        self.lease = Lease.objects.create(
            property=self.property, unit=self.unit, tenant=self.tenant, primary_tenant=self.tenant,
            start_date=date(2026, 1, 1), end_date=date(2026, 3, 31), monthly_rent="500", rent_amount="500",
            currency="OMR", billing_interval=1, billing_unit="month", billing_strategy="advance", billing_day=5,
            status=Lease.Status.ACTIVE,
        )
        self.lease.tenants.add(self.tenant)
        generate_rent_schedule(self.lease)

    def invoice(self, amount="500", *, due=date(2026, 10, 5)):
        return create_manual_invoice(lease=self.lease, issue_date=date(2026, 10, 1), due_date=due, description="Manual rent", amount=amount, actor=self.actor)

    def test_period_invoice_generation_is_idempotent_and_respects_horizon(self):
        first = generate_invoices(self.lease, today=date(2026, 1, 1), horizon=date(2026, 2, 28))
        second = generate_invoices(self.lease, today=date(2026, 1, 1), horizon=date(2026, 2, 28))
        self.assertEqual(len(first), 2); self.assertEqual(second, [])
        self.assertEqual(self.lease.invoices.count(), 2)
        self.assertRegex(first[0].number, r"^INV2026\d{4}$")
        self.assertEqual(first[0].line_items.get().type, "rent")

    def test_full_and_partial_payments_recalculate_invoice(self):
        invoice = self.invoice()
        partial = record_payment(invoice=invoice, amount="125", method="cash", payment_date=date(2026, 10, 2), actor=self.actor)
        invoice.refresh_from_db(); self.assertEqual(invoice.status, Invoice.Status.PARTIAL); self.assertEqual(invoice.amount_paid, Decimal("125.000"))
        record_payment(invoice=invoice, amount="375", method="bank_transfer", payment_date=date(2026, 10, 3), actor=self.actor)
        invoice.refresh_from_db(); self.assertEqual(invoice.status, Invoice.Status.PAID); self.assertEqual(invoice.balance, Decimal("0.000"))
        self.assertEqual(partial.status, Payment.Status.CONFIRMED)

    def test_pending_proof_reserves_balance_and_can_be_confirmed(self):
        invoice = self.invoice()
        proof = SimpleUploadedFile("receipt.pdf", b"%PDF-test", content_type="application/pdf")
        payment = record_payment(invoice=invoice, amount="400", method="bank_transfer", payment_date=date(2026, 10, 2), actor=self.actor, proof=proof, auto_confirm=False)
        self.assertEqual(payment.status, Payment.Status.PENDING); self.assertEqual(invoice.balance, Decimal("500.000"))
        with self.assertRaisesMessage(ValidationError, "available invoice balance"):
            record_payment(invoice=invoice, amount="101", method="cash", payment_date=date(2026, 10, 2), actor=self.actor)
        verify_payment(payment, confirmed=True, actor=self.actor, notes="Matched statement")
        invoice.refresh_from_db(); payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.CONFIRMED); self.assertEqual(invoice.status, Invoice.Status.PARTIAL)
        self.assertEqual(payment.proofs.get().status, "accepted")

    def test_rejected_payment_removes_allocations_and_is_terminal(self):
        invoice = self.invoice(); payment = Payment.objects.create(reference="PAY-REJECT", invoice=invoice, tenant=self.tenant, amount="50", currency="OMR", status=Payment.Status.PENDING)
        verify_payment(payment, confirmed=False, actor=self.actor, notes="Unreadable proof")
        payment.refresh_from_db(); self.assertEqual(payment.status, Payment.Status.CANCELLED)
        with self.assertRaisesMessage(ValidationError, "already been reviewed"): verify_payment(payment, confirmed=True, actor=self.actor)

    def test_multi_invoice_allocation_is_atomic_and_prevents_overflow(self):
        first = self.invoice("200"); second = create_manual_invoice(lease=self.lease, issue_date=date(2026, 11, 1), due_date=date(2026, 11, 5), description="Second", amount="300")
        payment = Payment.objects.create(reference="PAY-MULTI", tenant=self.tenant, amount="500", currency="OMR")
        complete_payment(payment.pk, {first.pk: Decimal("200"), second.pk: Decimal("300")})
        first.refresh_from_db(); second.refresh_from_db(); self.assertEqual(first.status, "paid"); self.assertEqual(second.status, "paid")
        overflow = Payment.objects.create(reference="PAY-OVER", tenant=self.tenant, amount="10", currency="OMR")
        with self.assertRaises(ValidationError): complete_payment(overflow.pk, {first.pk: Decimal("10")})
        self.assertFalse(overflow.allocations.exists())

    def test_payment_form_rejects_unsafe_proof(self):
        form = PaymentForm(data={"amount": "10", "method": "cash", "payment_date": "2026-10-01"}, files={"proof": SimpleUploadedFile("proof.exe", b"x")})
        self.assertFalse(form.is_valid()); self.assertIn("proof", form.errors)

    def test_signed_link_is_bound_to_invoice_version(self):
        invoice = self.invoice(); token = signed_invoice_token(invoice)
        self.assertEqual(invoice_from_signed_token(token), invoice)
        invoice.public_link_version += 1; invoice.save(update_fields=("public_link_version",))
        with self.assertRaises(signing.BadSignature): invoice_from_signed_token(token)

    def test_pdf_artifact_is_valid_and_reused(self):
        invoice = self.invoice(); first = ensure_invoice_pdf(invoice); second = ensure_invoice_pdf(invoice)
        self.assertEqual(first.pk, second.pk); self.assertTrue(InvoicePdfArtifact.objects.filter(invoice=invoice).exists())
        with first.file.open("rb") as handle: self.assertTrue(handle.read(8).startswith(b"%PDF-1."))

    def test_gateway_start_is_idempotent(self):
        invoice = self.invoice(); first = start_payment_attempt(invoice, gateway="manual", idempotency_key="same-key"); second = start_payment_attempt(invoice, gateway="manual", idempotency_key="same-key")
        self.assertEqual(first.pk, second.pk); self.assertTrue(first.external_id.startswith("manual-"))

    def test_gateway_cannot_be_disabled_with_pending_attempts(self):
        invoice = self.invoice(); start_payment_attempt(invoice, gateway="manual")
        self.client.force_login(self.actor)
        response = self.client.post("/settings/payment-gateway/", {"bank_name": "Test Bank", "secret_reference": "PAYMENT_WEBHOOK_SECRET"})
        self.assertContains(response, "Resolve pending payment attempts")

    def test_gateway_settlement_creates_exactly_one_payment(self):
        invoice = self.invoice(); attempt = start_payment_attempt(invoice, gateway="manual", idempotency_key="settle-key")
        result = {"gateway": "manual", "event_id": "evt-1", "external_id": attempt.external_id, "status": "settled", "amount": attempt.amount, "currency": attempt.currency, "payload": {"status": "settled"}}
        apply_gateway_result(**result); apply_gateway_result(**result)
        attempt.refresh_from_db(); invoice.refresh_from_db()
        self.assertEqual(attempt.status, PaymentAttempt.Status.SETTLED); self.assertIsNotNone(attempt.payment_id)
        self.assertEqual(invoice.payments.count(), 1); self.assertEqual(invoice.status, Invoice.Status.PAID)

    def test_gateway_mismatch_is_logged_without_payment(self):
        invoice = self.invoice(); attempt = start_payment_attempt(invoice, gateway="manual")
        apply_gateway_result(gateway="manual", event_id="evt-bad", external_id=attempt.external_id, status="settled", amount=Decimal("1"), currency="USD", payload={"bad": True})
        attempt.refresh_from_db(); self.assertEqual(attempt.status, PaymentAttempt.Status.PENDING); self.assertIsNone(attempt.payment_id)
        self.assertTrue(PaymentAnomaly.objects.filter(code="amount_currency_mismatch").exists())

    def test_webhook_rejects_invalid_signature(self):
        invoice = self.invoice(); attempt = start_payment_attempt(invoice, gateway="manual")
        body = json.dumps({"event_id": "evt-signature", "external_id": attempt.external_id, "status": "settled", "amount": str(attempt.amount), "currency": attempt.currency}).encode()
        with patch.dict("os.environ", {"PAYMENT_WEBHOOK_SECRET": "correct-secret"}): process_webhook("manual", body, "invalid")
        attempt.refresh_from_db(); self.assertEqual(attempt.status, PaymentAttempt.Status.PENDING); self.assertIsNone(attempt.payment_id)
        self.assertTrue(PaymentAnomaly.objects.filter(code="invalid_signature").exists())

    def test_paid_invoice_cannot_be_voided(self):
        invoice = self.invoice(); record_payment(invoice=invoice, amount="500", method="cash", payment_date=date(2026, 10, 1), actor=self.actor)
        with self.assertRaisesMessage(ValidationError, "confirmed payments"): void_invoice(invoice, actor=self.actor, reason="Duplicate")

    def test_staff_and_public_invoice_pages_render(self):
        invoice = self.invoice(); self.client.force_login(self.actor)
        self.assertContains(self.client.get(f"/invoices/{invoice.pk}/"), invoice.number)
        self.assertContains(self.client.get("/settings/payment-gateway/"), "Payment gateway")
        self.client.logout(); self.assertContains(self.client.get(f"/pay/invoices/{signed_invoice_token(invoice)}/"), "Amount due")
