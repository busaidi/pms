from datetime import datetime, time, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from billing.models import Invoice, InvoiceLineItem
from billing.services import normalize_amount, recalculate_invoice
from properties.models import Lease

from .models import UtilityMeter, UtilityReading
from django.utils.translation import gettext_lazy as _


def _reading_reference():
    prefix = f"UTL{timezone.localdate().year}"
    last = UtilityReading.objects.filter(reference__startswith=prefix).order_by("-reference").values_list("reference", flat=True).first()
    return f"{prefix}{int(last[len(prefix):]) + 1 if last else 1:05d}"


@transaction.atomic
def record_utility_reading(*, meter, reading_date, current_reading, actor, notes=""):
    meter = UtilityMeter.objects.select_for_update().get(pk=meter.pk)
    if not meter.is_active:
        raise ValidationError(_("The meter is inactive."))
    previous = meter.readings.filter(reading_kind=UtilityReading.Kind.READING).order_by("-reading_date", "-pk").first()
    current = Decimal(str(current_reading))
    previous_value = previous.current_reading if previous else Decimal("0")
    if previous and reading_date <= previous.reading_date:
        raise ValidationError(_("Reading dates must advance chronologically."))
    if current < previous_value:
        raise ValidationError(_("Current reading cannot be lower than the previous reading."))
    consumption = current - previous_value
    aware = timezone.make_aware(datetime.combine(reading_date, time(hour=12)))
    reading = UtilityReading(meter=meter, read_at=aware, value=current, previous_value=previous_value, rate=meter.rate, charge=normalize_amount(consumption * meter.rate, meter.currency), notes=notes, recorded_by=actor, reading_kind=UtilityReading.Kind.READING, reading_date=reading_date, period_start=(previous.reading_date + timedelta(days=1)) if previous else reading_date, period_end=reading_date, previous_reading_record=previous, current_reading=current, consumption=consumption, currency=meter.currency, reference=_reading_reference())
    reading.full_clean(); reading.save(); return reading


@transaction.atomic
def update_utility_reading(reading, *, current_reading, notes=""):
    reading = UtilityReading.objects.select_for_update().get(pk=reading.pk)
    if reading.invoice_line_item_id or reading.dependent_readings.exists():
        raise ValidationError(_("Billed readings and readings used by later entries cannot be changed."))
    current = Decimal(str(current_reading)); previous = reading.previous_value or Decimal("0")
    if current < previous: raise ValidationError(_("Current reading cannot be lower than the previous reading."))
    reading.current_reading = current; reading.value = current; reading.consumption = current - previous; reading.charge = normalize_amount(reading.consumption * reading.rate, reading.currency); reading.notes = notes
    reading.full_clean(); reading.save(); return reading


@transaction.atomic
def correct_utility_reading(reading, *, adjustment_consumption, actor, notes=""):
    original = UtilityReading.objects.select_for_update().get(pk=reading.pk)
    adjustment = Decimal(str(adjustment_consumption))
    if adjustment == 0: raise ValidationError(_("An adjustment cannot be zero."))
    aware = timezone.now()
    correction = UtilityReading(meter=original.meter, read_at=aware, value=original.current_reading, previous_value=original.current_reading, rate=original.rate, charge=normalize_amount(adjustment * original.rate, original.currency), notes=notes, recorded_by=actor, reading_kind=UtilityReading.Kind.ADJUSTMENT, reading_date=timezone.localdate(), period_start=original.period_start, period_end=original.period_end, current_reading=original.current_reading, consumption=adjustment, adjustment_consumption=adjustment, currency=original.currency, reference=_reading_reference(), corrects_reading=original)
    correction.full_clean(); correction.save(); return correction


@transaction.atomic
def bill_utility_readings(readings, *, actor=None):
    ids = [reading.pk for reading in readings]
    locked = (
        UtilityReading.objects.select_for_update(of=("self",))
        .filter(pk__in=ids, invoice_line_item__isnull=True)
        .select_related("meter__unit")
    )
    billed = []
    for reading in locked:
        lease = Lease.objects.filter(unit=reading.meter.unit, status=Lease.Status.ACTIVE).first()
        if not lease:
            raise ValidationError(
                _("%(unit)s has no active lease.") % {"unit": reading.meter.unit}
            )
        if lease.currency != reading.currency: raise ValidationError(_("Utility and lease currencies must match."))
        invoice = Invoice.objects.filter(lease=lease, status__in=(Invoice.Status.PENDING, Invoice.Status.PARTIAL, Invoice.Status.OVERDUE), due_date__gte=reading.period_end or reading.reading_date).order_by("due_date").first()
        if not invoice:
            raise ValidationError(
                _("No open invoice is available for %(lease)s.")
                % {"lease": lease.reference}
            )
        amount = normalize_amount(reading.consumption * reading.rate, reading.currency)
        description = f"{reading.meter.utility_name or reading.meter.get_kind_display()} {reading.period_start} – {reading.period_end}: {reading.consumption:.3f} {reading.meter.unit_of_measure}"
        line = InvoiceLineItem.objects.create(invoice=invoice, type=InvoiceLineItem.Type.UTILITY, description=description, quantity=reading.consumption, unit_price=reading.rate, total=amount, sort_order=invoice.line_items.count())
        totals = invoice.line_items.aggregate(total=Sum("total"))["total"] or Decimal("0")
        invoice.subtotal = totals; invoice.total = totals; invoice.save(update_fields=("subtotal", "total", "updated_at")); recalculate_invoice(invoice)
        reading.invoice_line_item = line; reading.save(update_fields=("invoice_line_item",)); billed.append(reading)
    return billed
