import hashlib
import json
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from django.core import signing
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import connection, transaction
from django.db.models import Q, Sum
from django.utils import timezone

from properties.models import Lease, RentSchedule

from .models import Invoice, InvoiceLineItem, InvoicePdfArtifact, Payment, PaymentAllocation, PaymentProof
from django.utils.translation import gettext_lazy as _


CURRENCY_DECIMALS = {"OMR": 3, "BHD": 3, "KWD": 3, "JOD": 3, "JPY": 0}


def normalize_amount(value, currency="OMR"):
    places = CURRENCY_DECIMALS.get(currency.upper(), 2)
    quantum = Decimal("1").scaleb(-places)
    return Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP)


def _next_reference(model, prefix, field="number"):
    year_prefix = f"{prefix}{timezone.localdate().year}"
    if connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", [f"pms-reference:{year_prefix}"])
    last = model.objects.select_for_update().filter(**{f"{field}__startswith": year_prefix}).order_by(f"-{field}").values_list(field, flat=True).first()
    suffix = last[len(year_prefix):] if last else ""
    sequence = int(suffix) + 1 if suffix.isdigit() else 1
    return f"{year_prefix}{sequence:04d}"


def _two_month_horizon(today):
    month = today.month - 1 + 2
    year = today.year + month // 12
    month = month % 12 + 1
    if month == 12:
        following = date(year + 1, 1, 1)
    else:
        following = date(year, month + 1, 1)
    return following.fromordinal(following.toordinal() - 1)


def _queue_invoice_pdfs(invoice_ids):
    from core.tasks import generate_invoice_pdf_artifact
    for invoice_id in invoice_ids:
        generate_invoice_pdf_artifact.delay(invoice_id)


@transaction.atomic
def generate_invoices(lease=None, *, today=None, horizon=None):
    today = today or timezone.localdate()
    horizon = horizon or _two_month_horizon(today)
    leases = Lease.objects.select_for_update().filter(status=Lease.Status.ACTIVE, archived_at__isnull=True)
    if lease is not None:
        leases = leases.filter(pk=lease.pk)
    created = []
    for locked_lease in leases:
        schedules = locked_lease.rent_schedule.filter(period_start__lte=horizon).order_by("period_start", "pk")
        for schedule in schedules:
            if schedule.period_start is None or schedule.period_end is None:
                continue
            invoice = Invoice.objects.filter(lease=locked_lease, period_start=schedule.period_start).first()
            if invoice:
                if schedule.status == RentSchedule.Status.SCHEDULED:
                    schedule.status = RentSchedule.Status.INVOICED
                    schedule.save(update_fields=("status",))
                continue
            amount = normalize_amount(schedule.amount, schedule.currency)
            reference = _next_reference(Invoice, "INV")
            invoice = Invoice(
                number=reference,
                lease=locked_lease,
                period_start=schedule.period_start,
                period_end=schedule.period_end,
                issue_date=schedule.period_start,
                due_date=schedule.due_date,
                currency=schedule.currency,
                subtotal=amount,
                total=amount,
                status=Invoice.Status.OVERDUE if schedule.due_date < today else Invoice.Status.PENDING,
            )
            invoice.full_clean(); invoice.save()
            InvoiceLineItem.objects.create(
                invoice=invoice,
                type=InvoiceLineItem.Type.RENT,
                description=f"Rent {schedule.period_start:%d %b %Y} – {schedule.period_end:%d %b %Y}",
                quantity=Decimal("1"),
                unit_price=amount,
                total=amount,
            )
            schedule.status = RentSchedule.Status.INVOICED
            schedule.save(update_fields=("status",))
            created.append(invoice)
    if created:
        transaction.on_commit(lambda: _queue_invoice_pdfs([invoice.pk for invoice in created]))
    return created


@transaction.atomic
def create_manual_invoice(*, lease, issue_date, due_date, description, amount, actor=None, notes=""):
    lease = Lease.objects.select_for_update().get(pk=lease.pk)
    normalized = normalize_amount(amount, lease.currency)
    if normalized <= 0:
        raise ValidationError(_("Invoice amount must be positive."))
    invoice = Invoice(
        number=_next_reference(Invoice, "INV"), lease=lease, issue_date=issue_date, due_date=due_date,
        currency=lease.currency, subtotal=normalized, total=normalized, status=Invoice.Status.PENDING, notes=notes,
    )
    invoice.full_clean(); invoice.save()
    InvoiceLineItem.objects.create(invoice=invoice, type=InvoiceLineItem.Type.MANUAL, description=description, quantity=1, unit_price=normalized, total=normalized)
    recalculate_invoice(invoice)
    return invoice


def recalculate_invoice(invoice, *, today=None):
    today = today or timezone.localdate()
    paid = invoice.allocations.filter(payment__status=Payment.Status.CONFIRMED).aggregate(total=Sum("amount"))["total"] or Decimal("0")
    invoice.amount_paid = paid
    if invoice.status not in (Invoice.Status.CANCELLED, Invoice.Status.VOID):
        if paid >= invoice.total:
            invoice.status = Invoice.Status.PAID
        elif paid > 0:
            invoice.status = Invoice.Status.PARTIAL
        elif invoice.due_date < today:
            invoice.status = Invoice.Status.OVERDUE
        else:
            invoice.status = Invoice.Status.PENDING
    invoice.save(update_fields=("amount_paid", "status", "updated_at"))
    return invoice


def _invoice_tenant_matches(invoice, tenant_id):
    return invoice.lease.tenant_id == tenant_id or invoice.lease.tenants.filter(pk=tenant_id).exists()


@transaction.atomic
def complete_payment(payment_id: int, allocations: dict[int, Decimal]) -> Payment:
    payment = (
        Payment.objects.select_for_update(of=("self",))
        .select_related("tenant")
        .get(pk=payment_id)
    )
    if payment.status not in (Payment.Status.PENDING, Payment.Status.CONFIRMED):
        raise ValidationError(_("Only pending or confirmed payments can be allocated."))
    normalized = {int(key): normalize_amount(value, payment.currency) for key, value in allocations.items()}
    requested_total = sum(normalized.values(), Decimal("0"))
    if requested_total <= 0 or requested_total > payment.amount:
        raise ValidationError(_("Allocation total must be positive and cannot exceed the payment amount."))
    invoices = {item.pk: item for item in Invoice.objects.select_for_update().filter(pk__in=normalized)}
    if set(invoices) != set(normalized):
        raise ValidationError(_("One or more invoices do not exist."))
    old_invoice_ids = set(payment.allocations.values_list("invoice_id", flat=True))
    for invoice_id, amount in normalized.items():
        invoice = invoices[invoice_id]
        if not _invoice_tenant_matches(invoice, payment.tenant_id):
            raise ValidationError(_("A payment can only be allocated to its tenant's invoices."))
        if invoice.currency != payment.currency:
            raise ValidationError(_("Payment and invoice currencies must match."))
        other_paid = invoice.allocations.filter(payment__status=Payment.Status.CONFIRMED).exclude(payment=payment).aggregate(total=Sum("amount"))["total"] or Decimal("0")
        if amount <= 0 or amount > invoice.total - other_paid:
            raise ValidationError(
                _("Allocation exceeds the balance for invoice %(invoice)s.")
                % {"invoice": invoice.number}
            )
    payment.allocations.all().delete()
    for invoice_id, amount in normalized.items():
        PaymentAllocation.objects.create(payment=payment, invoice=invoices[invoice_id], amount=amount)
    payment.status = Payment.Status.CONFIRMED
    payment.paid_at = payment.paid_at or timezone.now()
    payment.verified_at = payment.verified_at or timezone.now()
    payment.save(update_fields=("status", "paid_at", "verified_at", "updated_at"))
    for invoice in Invoice.objects.filter(pk__in=old_invoice_ids | set(invoices)):
        recalculate_invoice(invoice)
    return payment


@transaction.atomic
def record_payment(*, invoice, amount, method, payment_date, actor=None, proof=None, notes="", auto_confirm=True, gateway="", gateway_reference=""):
    invoice = Invoice.objects.select_for_update(of=("self",)).select_related("lease__primary_tenant", "lease__tenant").get(pk=invoice.pk)
    if invoice.status not in {Invoice.Status.PENDING, Invoice.Status.PARTIAL, Invoice.Status.OVERDUE}:
        raise ValidationError(_("This invoice is not payable."))
    normalized = normalize_amount(amount, invoice.currency)
    pending = invoice.payments.filter(status=Payment.Status.PENDING).aggregate(total=Sum("amount"))["total"] or Decimal("0")
    available = invoice.balance - pending
    if normalized <= 0 or normalized > available:
        raise ValidationError(
            _("Amount exceeds the available invoice balance of %(amount)s.")
            % {"amount": available}
        )
    tenant = invoice.lease.primary_tenant or invoice.lease.tenant
    should_confirm = auto_confirm
    payment = Payment.objects.create(
        reference=_next_reference(Payment, "PAY", "reference"), invoice=invoice, tenant=tenant, amount=normalized,
        currency=invoice.currency, method=method, gateway=gateway, gateway_reference=gateway_reference,
        status=Payment.Status.CONFIRMED if should_confirm else Payment.Status.PENDING,
        payment_date=payment_date, paid_at=timezone.now() if should_confirm else None, recorded_by=actor,
        confirmed_by=actor if should_confirm else None, verified_by=actor if should_confirm else None,
        verified_at=timezone.now() if should_confirm else None, notes=notes,
    )
    if proof:
        PaymentProof.objects.create(
            payment=payment, file=proof, original_name=proof.name, mime_type=getattr(proof, "content_type", "") or "application/octet-stream",
            size=proof.size, status=PaymentProof.Status.ACCEPTED if should_confirm else PaymentProof.Status.PENDING,
            reviewed_at=timezone.now() if should_confirm else None, reviewed_by=actor if should_confirm else None,
        )
    if should_confirm:
        complete_payment(payment.pk, {invoice.pk: normalized})
    return payment


@transaction.atomic
def verify_payment(payment, *, confirmed, actor, notes=""):
    payment = (
        Payment.objects.select_for_update(of=("self",))
        .select_related("invoice")
        .get(pk=payment.pk)
    )
    if payment.status != Payment.Status.PENDING:
        raise ValidationError(_("Payment has already been reviewed."))
    payment.verified_by = actor; payment.verified_at = timezone.now()
    payment.notes = notes or payment.notes
    if confirmed:
        if not payment.invoice_id:
            raise ValidationError(_("Payment has no invoice."))
        payment.confirmed_by = actor
        payment.save(update_fields=("confirmed_by", "verified_by", "verified_at", "notes", "updated_at"))
        complete_payment(payment.pk, {payment.invoice_id: payment.amount})
        payment.proofs.update(status=PaymentProof.Status.ACCEPTED, reviewed_by=actor, reviewed_at=timezone.now(), review_notes=notes)
    else:
        affected = list(payment.allocations.values_list("invoice_id", flat=True))
        payment.allocations.all().delete()
        payment.status = Payment.Status.CANCELLED; payment.cancellation_reason = notes
        payment.save(update_fields=("status", "cancellation_reason", "verified_by", "verified_at", "notes", "updated_at"))
        payment.proofs.update(status=PaymentProof.Status.REJECTED, reviewed_by=actor, reviewed_at=timezone.now(), review_notes=notes)
        for invoice in Invoice.objects.filter(Q(pk__in=affected) | Q(pk=payment.invoice_id)).distinct(): recalculate_invoice(invoice)
    return payment


@transaction.atomic
def void_invoice(invoice, *, actor, reason):
    invoice = Invoice.objects.select_for_update().get(pk=invoice.pk)
    if invoice.allocated_total > 0:
        raise ValidationError(_("An invoice with confirmed payments cannot be voided."))
    if invoice.status in {Invoice.Status.VOID, Invoice.Status.CANCELLED}:
        raise ValidationError(_("Invoice is already closed."))
    invoice.status = Invoice.Status.VOID; invoice.void_reason = reason; invoice.voided_by = actor; invoice.voided_at = timezone.now()
    invoice.save(update_fields=("status", "void_reason", "voided_by", "voided_at", "updated_at"))
    return invoice


def signed_invoice_token(invoice):
    return signing.dumps({"invoice": invoice.pk, "version": invoice.public_link_version}, salt="billing.invoice-payment", compress=True)


def invoice_from_signed_token(token, *, max_age=7 * 24 * 60 * 60):
    data = signing.loads(token, salt="billing.invoice-payment", max_age=max_age)
    invoice = Invoice.objects.select_related("lease__primary_tenant", "lease__property", "lease__unit").get(pk=data["invoice"])
    if data.get("version") != invoice.public_link_version:
        raise signing.BadSignature("Payment link was revoked.")
    return invoice


def _pdf_bytes(lines):
    def esc(value):
        return str(value).encode("ascii", "replace").decode().replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    commands = ["BT", "/F1 12 Tf", "50 790 Td"]
    for index, line in enumerate(lines):
        if index: commands.append("0 -20 Td")
        commands.append(f"({esc(line)}) Tj")
    commands.append("ET")
    stream = "\n".join(commands).encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    result = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(len(result)); result.extend(f"{index} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = len(result); result.extend(f"xref\n0 {len(objects)+1}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]: result.extend(f"{offset:010d} 00000 n \n".encode())
    result.extend(f"trailer << /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return bytes(result)


@transaction.atomic
def ensure_invoice_pdf(invoice):
    invoice = Invoice.objects.select_for_update(of=("self",)).select_related("lease__property", "lease__unit", "lease__primary_tenant").prefetch_related("line_items").get(pk=invoice.pk)
    payload = {"number": invoice.number, "total": str(invoice.total), "paid": str(invoice.amount_paid), "updated": invoice.updated_at.isoformat(), "lines": [(x.description, str(x.total)) for x in invoice.line_items.all()]}
    fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    artifact = InvoicePdfArtifact.objects.filter(invoice=invoice).first()
    if artifact and artifact.fingerprint == fingerprint and artifact.file.storage.exists(artifact.file.name):
        return artifact
    lines = ["OMAN SKYLIGHT PROPERTY MANAGEMENT", f"Invoice {invoice.number}", f"Property: {invoice.lease.property.name}", f"Tenant: {invoice.lease.primary_tenant or invoice.lease.tenant}", f"Due: {invoice.due_date}"]
    lines += [f"{item.description}: {invoice.currency} {item.total:.3f}" for item in invoice.line_items.all()]
    lines += [f"Total: {invoice.currency} {invoice.total:.3f}", f"Paid: {invoice.currency} {invoice.amount_paid:.3f}", f"Balance: {invoice.currency} {invoice.balance:.3f}"]
    if artifact and artifact.file.name: artifact.file.storage.delete(artifact.file.name)
    artifact = artifact or InvoicePdfArtifact(invoice=invoice)
    artifact.fingerprint = fingerprint
    artifact.file.save(f"{invoice.number}.pdf", ContentFile(_pdf_bytes(lines)), save=False)
    artifact.save()
    return artifact
