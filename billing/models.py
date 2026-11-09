from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q, Sum
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class Invoice(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        PENDING = "pending", _("Pending")
        ISSUED = "issued", _("Issued (legacy)")
        PARTIAL = "partial", _("Partially paid")
        PAID = "paid", _("Paid")
        OVERDUE = "overdue", _("Overdue")
        CANCELLED = "cancelled", _("Cancelled")
        VOID = "void", _("Void")

    number = models.CharField(max_length=40, unique=True)
    lease = models.ForeignKey("properties.Lease", on_delete=models.PROTECT, related_name="invoices")
    period_start = models.DateField(null=True, blank=True)
    period_end = models.DateField(null=True, blank=True)
    issue_date = models.DateField()
    due_date = models.DateField()
    currency = models.CharField(max_length=3, default="OMR")
    subtotal = models.DecimalField(max_digits=14, decimal_places=3, default=0)
    tax = models.DecimalField(max_digits=14, decimal_places=3, default=0)
    total = models.DecimalField(max_digits=14, decimal_places=3, default=0)
    amount_paid = models.DecimalField(max_digits=14, decimal_places=3, default=0)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    notes = models.TextField(blank=True)
    void_reason = models.TextField(blank=True)
    voided_at = models.DateTimeField(null=True, blank=True)
    voided_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="voided_invoices")
    public_link_version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-issue_date", "-id")
        constraints = [models.UniqueConstraint(fields=("lease", "period_start"), condition=Q(period_start__isnull=False), name="unique_lease_invoice_period")]

    @property
    def allocated_total(self):
        return self.allocations.filter(payment__status=Payment.Status.CONFIRMED).aggregate(value=Sum("amount"))["value"] or Decimal("0")

    @property
    def balance(self):
        return max(self.total - self.allocated_total, Decimal("0"))

    def clean(self):
        if self.due_date < self.issue_date:
            raise ValidationError({"due_date": _("Due date must be on or after issue date.")})
        if self.period_start and self.period_end and self.period_end < self.period_start:
            raise ValidationError({"period_end": _("Period end must be on or after period start.")})
        if self.total < 0:
            raise ValidationError({"total": _("Invoice total cannot be negative.")})

    def save(self, *args, **kwargs):
        self.currency = self.currency.upper()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.number


class InvoiceLineItem(models.Model):
    class Type(models.TextChoices):
        RENT = "rent", _("Rent")
        UTILITY = "utility", _("Utility")
        MANUAL = "manual", _("Manual")

    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="line_items")
    type = models.CharField(max_length=16, choices=Type.choices, default=Type.MANUAL)
    description = models.CharField(max_length=255)
    quantity = models.DecimalField(max_digits=10, decimal_places=3, default=1)
    unit_price = models.DecimalField(max_digits=14, decimal_places=3)
    total = models.DecimalField(max_digits=14, decimal_places=3)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("sort_order", "id")

    def clean(self):
        if self.quantity <= 0 or self.unit_price < 0 or self.total < 0:
            raise ValidationError(_("Invoice line amounts must be positive."))

    def __str__(self):
        return self.description


class Payment(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        CONFIRMED = "confirmed", _("Confirmed")
        CANCELLED = "cancelled", _("Cancelled")

    class Method(models.TextChoices):
        CASH = "cash", _("Cash")
        BANK_TRANSFER = "bank_transfer", _("Bank transfer")
        E_WALLET = "e_wallet", _("E-wallet")
        OTHER = "other", _("Other")
        GATEWAY = "gateway", _("Payment gateway")

    reference = models.CharField(max_length=80, unique=True)
    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, null=True, blank=True, related_name="payments")
    tenant = models.ForeignKey("properties.Tenant", on_delete=models.PROTECT, related_name="payments")
    amount = models.DecimalField(max_digits=14, decimal_places=3)
    currency = models.CharField(max_length=3, default="OMR")
    method = models.CharField(max_length=40, choices=Method.choices, default=Method.BANK_TRANSFER)
    gateway = models.CharField(max_length=60, blank=True)
    gateway_reference = models.CharField(max_length=160, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    payment_date = models.DateField(default=timezone.localdate)
    paid_at = models.DateTimeField(null=True, blank=True)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="recorded_payments")
    confirmed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="confirmed_payments")
    verified_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="verified_payments")
    verified_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-payment_date", "-id")

    def clean(self):
        if self.amount <= 0:
            raise ValidationError({"amount": _("Payment amount must be positive.")})
        if self.invoice_id and self.currency.upper() != self.invoice.currency:
            raise ValidationError({"currency": _("Payment currency must match the invoice.")})

    def save(self, *args, **kwargs):
        self.currency = self.currency.upper()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.reference


class PaymentAllocation(models.Model):
    payment = models.ForeignKey(Payment, on_delete=models.CASCADE, related_name="allocations")
    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name="allocations")
    amount = models.DecimalField(max_digits=14, decimal_places=3)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("payment", "invoice"), name="unique_payment_invoice_allocation")]

    def clean(self):
        if self.amount <= 0:
            raise ValidationError({"amount": _("Allocation amount must be positive.")})
        if self.payment.currency != self.invoice.currency:
            raise ValidationError({"amount": _("Allocation currency does not match the invoice.")})


class PaymentProof(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", _("Pending review")
        ACCEPTED = "accepted", _("Accepted")
        REJECTED = "rejected", _("Rejected")

    payment = models.ForeignKey(Payment, on_delete=models.CASCADE, related_name="proofs")
    file = models.FileField(upload_to="payment-proofs/%Y/%m")
    original_name = models.CharField(max_length=255, blank=True)
    mime_type = models.CharField(max_length=120, blank=True)
    size = models.PositiveBigIntegerField(default=0)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    submitted_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    review_notes = models.TextField(blank=True)


class PaymentAttempt(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        SETTLED = "settled", _("Settled")
        FAILED = "failed", _("Failed")
        EXPIRED = "expired", _("Expired")
        CANCELED = "canceled", _("Canceled")

    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, null=True, blank=True, related_name="payment_attempts")
    payment = models.OneToOneField(Payment, on_delete=models.SET_NULL, null=True, blank=True, related_name="payment_attempt")
    gateway = models.CharField(max_length=60)
    external_id = models.CharField(max_length=160, blank=True, db_index=True)
    idempotency_key = models.CharField(max_length=80, unique=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    amount = models.DecimalField(max_digits=14, decimal_places=3, default=0)
    currency = models.CharField(max_length=3, default="OMR")
    checkout_url = models.URLField(blank=True)
    checkout_instructions = models.JSONField(default=dict, blank=True)
    request_payload = models.JSONField(default=dict, blank=True)
    response_payload = models.JSONField(default=dict, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    settled_at = models.DateTimeField(null=True, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)
    expired_at = models.DateTimeField(null=True, blank=True)
    canceled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("gateway", "external_id"), condition=~Q(external_id=""), name="unique_gateway_external_attempt")]

    def save(self, *args, **kwargs):
        self.currency = self.currency.upper()
        super().save(*args, **kwargs)

    @property
    def is_terminal(self):
        return self.status in {self.Status.SETTLED, self.Status.FAILED, self.Status.EXPIRED, self.Status.CANCELED}


class PaymentWebhook(models.Model):
    gateway = models.CharField(max_length=60)
    event_id = models.CharField(max_length=160)
    attempt = models.ForeignKey(PaymentAttempt, on_delete=models.SET_NULL, null=True, blank=True, related_name="webhooks")
    signature_valid = models.BooleanField(default=False)
    payload = models.JSONField(default=dict)
    processed_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True)
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("gateway", "event_id"), name="unique_gateway_webhook_event")]


class PaymentAnomaly(models.Model):
    gateway = models.CharField(max_length=60)
    event_id = models.CharField(max_length=160, blank=True)
    attempt = models.ForeignKey(PaymentAttempt, on_delete=models.SET_NULL, null=True, blank=True, related_name="anomalies")
    code = models.CharField(max_length=60)
    detail = models.TextField()
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)


class InvoicePdfArtifact(models.Model):
    invoice = models.OneToOneField(Invoice, on_delete=models.CASCADE, related_name="pdf_artifact")
    fingerprint = models.CharField(max_length=64)
    file = models.FileField(upload_to="invoice-pdfs/%Y/%m")
    generated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"PDF · {self.invoice.number}"
