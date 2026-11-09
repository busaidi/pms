import hashlib
import hmac
import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import Invoice, PaymentAnomaly, PaymentAttempt, PaymentWebhook
from .services import record_payment
from django.utils.translation import gettext_lazy as _


@dataclass(frozen=True)
class GatewayStartResult:
    external_id: str
    checkout_url: str = ""
    instructions: dict = field(default_factory=dict)
    payload: dict = field(default_factory=dict)


class PaymentGateway:
    code = "base"
    label = "Base gateway"

    def start(self, attempt, return_url):
        raise NotImplementedError

    def verify_webhook(self, raw_body, signature):
        from integrations.models import Integration
        integration = Integration.objects.filter(kind=Integration.Kind.PAYMENT, provider=self.code).first()
        secret_name = integration.secret_reference if integration and integration.secret_reference else "PAYMENT_WEBHOOK_SECRET"
        secret = os.environ.get(secret_name, "")
        if not secret or not signature:
            return False
        expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)

    def parse_webhook(self, payload):
        return {
            "event_id": str(payload["event_id"]),
            "external_id": str(payload["external_id"]),
            "status": str(payload["status"]).lower(),
            "amount": Decimal(str(payload["amount"])),
            "currency": str(payload["currency"]).upper(),
        }

    def reconcile(self, attempt):
        return None


class ManualGateway(PaymentGateway):
    code = "manual"
    label = "Manual bank transfer"

    def start(self, attempt, return_url):
        from integrations.models import Integration
        integration = Integration.objects.filter(kind=Integration.Kind.PAYMENT, provider=self.code, is_enabled=True).first()
        config = integration.configuration if integration else {}
        return GatewayStartResult(
            external_id=f"manual-{uuid.uuid4().hex}",
            instructions={
                "title": "Bank transfer instructions",
                "reference": attempt.idempotency_key,
                "message": config.get("instructions") or "Transfer the exact amount and include this reference. Staff will confirm receipt.",
                "bank_name": config.get("bank_name", ""),
                "account_name": config.get("account_name", ""),
                "iban": config.get("iban", ""),
            },
        )


_registry = {ManualGateway.code: ManualGateway()}


def register_gateway(gateway):
    _registry[gateway.code] = gateway


def get_gateway(code):
    try:
        return _registry[code]
    except KeyError as error:
        raise ValidationError(_("Payment gateway is unavailable.")) from error


def gateway_choices():
    return [(code, driver.label) for code, driver in sorted(_registry.items())]


@transaction.atomic
def start_payment_attempt(invoice, *, gateway="manual", idempotency_key=None, return_url=""):
    from integrations.models import Integration
    integration = Integration.objects.filter(kind=Integration.Kind.PAYMENT, provider=gateway).first()
    if integration and not integration.is_enabled:
        raise ValidationError(_("Payment gateway is disabled."))
    invoice = Invoice.objects.select_for_update().get(pk=invoice.pk)
    if invoice.status not in {Invoice.Status.PENDING, Invoice.Status.PARTIAL, Invoice.Status.OVERDUE} or invoice.balance <= 0:
        raise ValidationError(_("This invoice is not payable."))
    idempotency_key = idempotency_key or uuid.uuid4().hex
    existing = PaymentAttempt.objects.filter(idempotency_key=idempotency_key).first()
    if existing:
        if existing.invoice_id != invoice.pk or existing.gateway != gateway:
            raise ValidationError(_("Idempotency key belongs to another payment request."))
        return existing
    attempt = PaymentAttempt.objects.create(
        invoice=invoice, gateway=gateway, idempotency_key=idempotency_key, status=PaymentAttempt.Status.PENDING,
        amount=invoice.balance, currency=invoice.currency, expires_at=timezone.now() + timedelta(minutes=30),
        request_payload={"invoice": invoice.number, "amount": str(invoice.balance), "currency": invoice.currency},
    )
    result = get_gateway(gateway).start(attempt, return_url)
    attempt.external_id = result.external_id; attempt.checkout_url = result.checkout_url
    attempt.checkout_instructions = result.instructions; attempt.response_payload = result.payload
    attempt.save(update_fields=("external_id", "checkout_url", "checkout_instructions", "response_payload", "updated_at"))
    return attempt


def _anomaly(gateway, code, detail, payload, *, event_id="", attempt=None):
    return PaymentAnomaly.objects.create(gateway=gateway, event_id=event_id, attempt=attempt, code=code, detail=detail, payload=payload)


@transaction.atomic
def apply_gateway_result(*, gateway, event_id, external_id, status, amount, currency, payload, signature_valid=True):
    webhook, created = PaymentWebhook.objects.get_or_create(
        gateway=gateway, event_id=event_id,
        defaults={"signature_valid": signature_valid, "payload": payload},
    )
    if not created and webhook.processed_at:
        return webhook.attempt
    if not signature_valid:
        webhook.error_message = "Invalid signature"; webhook.processed_at = timezone.now(); webhook.save(update_fields=("error_message", "processed_at"))
        _anomaly(gateway, "invalid_signature", "Webhook signature validation failed.", payload, event_id=event_id)
        return None
    attempt = (
        PaymentAttempt.objects.select_for_update(of=("self",))
        .filter(gateway=gateway, external_id=external_id)
        .select_related("invoice")
        .first()
    )
    webhook.attempt = attempt
    if not attempt:
        webhook.error_message = "Unknown attempt"; webhook.processed_at = timezone.now(); webhook.save(update_fields=("attempt", "error_message", "processed_at"))
        _anomaly(gateway, "unknown_attempt", "No payment attempt matched the provider reference.", payload, event_id=event_id)
        return None
    normalized_status = {"succeeded": "settled", "success": "settled", "cancelled": "canceled"}.get(status, status)
    terminal = {PaymentAttempt.Status.SETTLED, PaymentAttempt.Status.FAILED, PaymentAttempt.Status.EXPIRED, PaymentAttempt.Status.CANCELED}
    if attempt.is_terminal:
        if attempt.status != normalized_status:
            _anomaly(gateway, "terminal_conflict", f"Attempt is already {attempt.status}; received {normalized_status}.", payload, event_id=event_id, attempt=attempt)
        webhook.processed_at = timezone.now(); webhook.save(update_fields=("attempt", "processed_at"))
        return attempt
    if Decimal(str(amount)) != attempt.amount or currency.upper() != attempt.currency:
        webhook.error_message = "Amount or currency mismatch"; webhook.processed_at = timezone.now(); webhook.save(update_fields=("attempt", "error_message", "processed_at"))
        _anomaly(gateway, "amount_currency_mismatch", "Provider result does not match the payment attempt snapshot.", payload, event_id=event_id, attempt=attempt)
        return attempt
    if normalized_status not in terminal | {PaymentAttempt.Status.PENDING}:
        webhook.error_message = "Unsupported status"; webhook.processed_at = timezone.now(); webhook.save(update_fields=("attempt", "error_message", "processed_at"))
        _anomaly(gateway, "unsupported_status", f"Unsupported provider status: {normalized_status}", payload, event_id=event_id, attempt=attempt)
        return attempt
    if normalized_status == PaymentAttempt.Status.SETTLED:
        try:
            payment = record_payment(
                invoice=attempt.invoice, amount=attempt.amount, method="gateway", payment_date=timezone.localdate(), actor=None,
                auto_confirm=True, gateway=gateway, gateway_reference=external_id, notes=f"Settled by {gateway}",
            )
        except ValidationError as error:
            webhook.error_message = error.messages[0]; webhook.processed_at = timezone.now(); webhook.save(update_fields=("attempt", "error_message", "processed_at"))
            _anomaly(gateway, "invoice_not_payable", error.messages[0], payload, event_id=event_id, attempt=attempt)
            return attempt
        attempt.payment = payment; attempt.status = PaymentAttempt.Status.SETTLED; attempt.settled_at = timezone.now()
    elif normalized_status == PaymentAttempt.Status.FAILED:
        attempt.status = normalized_status; attempt.failed_at = timezone.now()
    elif normalized_status == PaymentAttempt.Status.EXPIRED:
        attempt.status = normalized_status; attempt.expired_at = timezone.now()
    elif normalized_status == PaymentAttempt.Status.CANCELED:
        attempt.status = normalized_status; attempt.canceled_at = timezone.now()
    attempt.response_payload = payload
    attempt.save()
    webhook.processed_at = timezone.now(); webhook.save(update_fields=("attempt", "processed_at"))
    return attempt


def process_webhook(gateway_code, raw_body, signature):
    driver = get_gateway(gateway_code)
    signature_valid = driver.verify_webhook(raw_body, signature)
    try:
        payload = json.loads(raw_body.decode())
        result = driver.parse_webhook(payload)
    except (KeyError, ValueError, TypeError, json.JSONDecodeError) as error:
        event_id = hashlib.sha256(raw_body).hexdigest()
        PaymentWebhook.objects.get_or_create(gateway=gateway_code, event_id=event_id, defaults={"signature_valid": signature_valid, "payload": {}, "error_message": "Malformed payload", "processed_at": timezone.now()})
        _anomaly(gateway_code, "malformed_payload", str(error), {}, event_id=event_id)
        return None
    return apply_gateway_result(gateway=gateway_code, payload=payload, signature_valid=signature_valid, **result)


@transaction.atomic
def reconcile_attempt(attempt):
    attempt = PaymentAttempt.objects.select_for_update().get(pk=attempt.pk)
    if attempt.is_terminal:
        return attempt
    if attempt.expires_at and attempt.expires_at <= timezone.now():
        attempt.status = PaymentAttempt.Status.EXPIRED; attempt.expired_at = timezone.now(); attempt.save(update_fields=("status", "expired_at", "updated_at"))
        return attempt
    result = get_gateway(attempt.gateway).reconcile(attempt)
    if result:
        return apply_gateway_result(gateway=attempt.gateway, event_id=f"reconcile-{attempt.pk}-{uuid.uuid4().hex}", external_id=attempt.external_id, payload=result, signature_valid=True, status=result["status"], amount=result["amount"], currency=result["currency"])
    return attempt
