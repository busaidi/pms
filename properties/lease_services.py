import calendar
from datetime import date, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import (DepositDeduction, DepositSettlement, Lease, LeaseNotificationEvent,
                     LeaseUnitHistory, Property, PropertyRate, RentSchedule, Tenant,
                     Unit, UnitRate, UnitType, UnitTypeRate)
from .services import current_rates, effective_unit_rates
from django.utils.translation import gettext_lazy as _


def add_months(value, months):
    month = value.month - 1 + months
    year = value.year + month // 12
    month = month % 12 + 1
    return value.replace(year=year, month=month, day=min(value.day, calendar.monthrange(year, month)[1]))


def active_leases():
    return Lease.objects.filter(status=Lease.Status.ACTIVE, archived_at__isnull=True)


def tenant_has_active_lease(tenant_ids, exclude=None):
    query = active_leases().filter(Q(tenant_id__in=tenant_ids) | Q(tenants__id__in=tenant_ids))
    if exclude: query = query.exclude(pk=exclude)
    return query.distinct().exists()


def _select_unit(unit_type):
    for unit in unit_type.units.filter(archived_at__isnull=True, status=Unit.Status.AVAILABLE).order_by("name"):
        if not active_leases().filter(Q(unit=unit) | Q(property=unit.property, unit__isnull=True)).exists():
            return unit
    raise ValidationError(_("No eligible unit is available for this unit type."))


def _rate_for(property_obj, unit=None):
    if unit is None:
        rate = current_rates(PropertyRate.objects.filter(property=property_obj)).first()
        return rate, "property_rate"
    items = effective_unit_rates(unit)
    if not items: return None, None
    rate = items[0]["rate"]
    return rate, "unit_rate" if isinstance(rate, UnitRate) else "unit_type_rate"


@transaction.atomic
def generate_rent_schedule(lease):
    protected_due_dates = set(
        lease.rent_schedule.exclude(status=RentSchedule.Status.SCHEDULED).values_list("due_date", flat=True)
    )
    lease.rent_schedule.filter(status=RentSchedule.Status.SCHEDULED).delete()
    lease.notification_events.filter(kind="expiration", status="pending").delete()
    if lease.end_date:
        LeaseNotificationEvent.objects.get_or_create(
            lease=lease,
            kind="expiration",
            scheduled_for=lease.end_date - timedelta(days=30),
            defaults={"payload": {"end_date": str(lease.end_date)}},
        )
    if not lease.rent_amount:
        return []
    cursor = lease.start_date
    end = lease.end_date or add_months(cursor, 12)
    rows = []
    while cursor <= end:
        if lease.billing_unit == "day": period_end = min(cursor + timedelta(days=lease.billing_interval - 1), end)
        elif lease.billing_unit == "week": period_end = min(cursor + timedelta(weeks=lease.billing_interval) - timedelta(days=1), end)
        elif lease.billing_unit == "year": period_end = min(add_months(cursor, 12 * lease.billing_interval) - timedelta(days=1), end)
        else: period_end = min(add_months(cursor, lease.billing_interval) - timedelta(days=1), end)
        if lease.billing_unit in {"day", "week"}:
            due = cursor if lease.billing_strategy == Lease.BillingStrategy.ADVANCE else period_end + timedelta(days=1)
        else:
            base_due = cursor.replace(day=min(lease.billing_day, calendar.monthrange(cursor.year, cursor.month)[1]))
            if base_due < cursor: base_due = add_months(base_due, 1)
            due = base_due if lease.billing_strategy == Lease.BillingStrategy.ADVANCE else period_end + timedelta(days=1)
        if due not in protected_due_dates:
            rows.append(RentSchedule(lease=lease, period_start=cursor, period_end=period_end, due_date=due, amount=lease.rent_amount, currency=lease.currency))
        cursor = period_end + timedelta(days=1)
    created = RentSchedule.objects.bulk_create(rows)
    return created


@transaction.atomic
def create_lease(*, property_obj, tenants, start_date, end_date=None, unit=None, unit_type=None,
                 rent_amount=None, currency=None, billing_interval=None, billing_unit=None,
                 billing_strategy="advance", billing_day=1, deposit_amount=0, notes=""):
    property_obj = Property.objects.select_for_update().get(pk=property_obj.pk)
    tenants = list(Tenant.objects.select_for_update().filter(pk__in=[item.pk for item in tenants], archived_at__isnull=True, is_active=True))
    if not tenants: raise ValidationError(_("Select at least one active tenant."))
    if tenant_has_active_lease([item.pk for item in tenants]): raise ValidationError(_("A selected tenant already has an active lease."))
    if unit_type:
        if unit_type.property_id != property_obj.pk: raise ValidationError(_("The unit type does not belong to this property."))
        unit = _select_unit(unit_type)
    if unit:
        unit = Unit.objects.select_for_update().get(pk=unit.pk)
        if not property_obj.supports_unit_inventory or unit.property_id != property_obj.pk: raise ValidationError(_("This unit cannot be leased from the selected property."))
        if unit.status in (Unit.Status.MAINTENANCE, Unit.Status.UNAVAILABLE): raise ValidationError(_("This unit is unavailable for lease."))
        if len(tenants) > unit.capacity:
            raise ValidationError(
                _("Unit capacity is %(capacity)s occupants.")
                % {"capacity": unit.capacity}
            )
        if active_leases().filter(Q(unit=unit) | Q(property=property_obj, unit__isnull=True)).exists(): raise ValidationError(_("This unit or property already has an active lease."))
    else:
        if not property_obj.supports_property_pricing: raise ValidationError(_("This property does not support whole-property rental."))
        if active_leases().filter(property=property_obj).exists(): raise ValidationError(_("This property already has an active lease."))
    rate, field = _rate_for(property_obj, unit)
    if rent_amount in (None, "") and not rate: raise ValidationError(_("The rental target has no effective rate."))
    amount = Decimal(str(rent_amount if rent_amount not in (None, "") else rate.amount))
    selected_currency = (currency or (rate.currency if rate else "OMR")).upper()
    lease = Lease(property=property_obj, unit=unit, tenant=tenants[0], primary_tenant=tenants[0], start_date=start_date, end_date=end_date,
                  rent_amount=amount, monthly_rent=amount, currency=selected_currency,
                  billing_interval=billing_interval or (rate.billing_interval if rate else 1), billing_unit=billing_unit or (rate.billing_unit if rate else "month"),
                  billing_strategy=billing_strategy, billing_day=billing_day, security_deposit=Decimal(str(deposit_amount or 0)),
                  is_custom_price=bool(rate and amount != rate.amount), notes=notes, status=Lease.Status.ACTIVE)
    if field: setattr(lease, field, rate)
    lease.full_clean(); lease.save(); lease.tenants.set(tenants)
    if unit: unit.status = Unit.Status.OCCUPIED; unit.save(update_fields=("status", "updated_at"))
    generate_rent_schedule(lease)
    return lease


def _free_unit(unit, excluding):
    if unit and not active_leases().filter(unit=unit).exclude(pk=excluding).exists() and unit.status != Unit.Status.MAINTENANCE:
        unit.status = Unit.Status.AVAILABLE; unit.save(update_fields=("status", "updated_at"))


@transaction.atomic
def terminate_lease(lease, *, end_date, reason, notes=""):
    lease = (
        Lease.objects.select_for_update(of=("self",))
        .select_related("unit")
        .get(pk=lease.pk)
    )
    if lease.status != Lease.Status.ACTIVE: raise ValidationError(_("Only active leases can be terminated."))
    if end_date < lease.start_date: raise ValidationError(_("Termination cannot precede the lease start date."))
    lease.end_date = end_date; lease.termination_date = timezone.localdate(); lease.termination_reason = reason; lease.notes = notes or lease.notes; lease.status = Lease.Status.TERMINATED
    lease.save(update_fields=("end_date", "termination_date", "termination_reason", "notes", "status", "updated_at")); _free_unit(lease.unit, lease.pk)
    lease.rent_schedule.filter(due_date__gt=end_date, status=RentSchedule.Status.SCHEDULED).update(status=RentSchedule.Status.WAIVED)
    return lease


@transaction.atomic
def move_lease(lease, *, target_unit, effective_date, reason="", actor=None):
    lease = (
        Lease.objects.select_for_update(of=("self",))
        .select_related("unit")
        .get(pk=lease.pk)
    )
    target = Unit.objects.select_for_update().get(pk=target_unit.pk)
    if lease.status != Lease.Status.ACTIVE or lease.unit_id is None: raise ValidationError(_("Only an active unit lease can be moved."))
    if target.pk == lease.unit_id: raise ValidationError(_("Choose a different unit."))
    if target.status in (Unit.Status.MAINTENANCE, Unit.Status.UNAVAILABLE) or active_leases().filter(Q(unit=target) | Q(property=target.property, unit__isnull=True)).exists(): raise ValidationError(_("The target unit is unavailable."))
    if lease.tenants.count() > target.capacity: raise ValidationError(_("The target unit capacity is too small."))
    old = lease.unit; lease.unit = target; lease.property = target.property; lease.save(update_fields=("unit", "property", "updated_at"))
    LeaseUnitHistory.objects.create(lease=lease, unit=target, from_unit=old, to_unit=target, moved_in_at=effective_date, effective_date=effective_date, reason=reason, transferred_by=actor)
    _free_unit(old, lease.pk); target.status = Unit.Status.OCCUPIED; target.save(update_fields=("status", "updated_at")); return lease


@transaction.atomic
def renew_lease(lease, *, end_date, rent_amount, confirmed_outstanding=False, deposit_handling="carry_forward"):
    lease = Lease.objects.select_for_update().get(pk=lease.pk)
    if lease.status != Lease.Status.ACTIVE: raise ValidationError(_("Only active leases can be renewed."))
    if not lease.end_date: raise ValidationError(_("Open-ended leases cannot be renewed."))
    if end_date <= lease.end_date: raise ValidationError(_("The renewal end date must be after the current lease end date."))
    if lease.outstanding_balance > 0 and not confirmed_outstanding:
        raise ValidationError(
            _("Lease has an outstanding balance of %(amount)s. Confirm to proceed.")
            % {"amount": lease.outstanding_balance}
        )
    lease.status = Lease.Status.RENEWED; lease.save(update_fields=("status", "updated_at"))
    if deposit_handling not in {"carry_forward", "refund_and_collect_new", "forfeit"}: raise ValidationError(_("Choose a valid deposit handling option."))
    deposit = lease.security_deposit if deposit_handling in {"carry_forward", "refund_and_collect_new"} else Decimal("0")
    if deposit_handling == "refund_and_collect_new":
        lease.deposit_refund_amount = lease.security_deposit; lease.deposit_refunded_at = timezone.now()
        lease.save(update_fields=("deposit_refund_amount", "deposit_refunded_at", "updated_at"))
    elif deposit_handling == "forfeit" and lease.security_deposit:
        settlement = DepositSettlement.objects.create(lease=lease, deposit_received=lease.security_deposit, original_amount=lease.security_deposit, currency=lease.currency, refund_amount=0, status=DepositSettlement.Status.SETTLED, settlement_date=timezone.localdate(), settled_at=timezone.now(), notes="Forfeited on renewal")
        DepositDeduction.objects.create(settlement=settlement, description="Forfeited on renewal", amount=lease.security_deposit)
    renewed = Lease.objects.create(property=lease.property, unit=lease.unit, tenant=lease.tenant, primary_tenant=lease.primary_tenant,
        previous_lease=lease, start_date=lease.end_date + timedelta(days=1), end_date=end_date, rent_amount=rent_amount, monthly_rent=rent_amount,
        currency=lease.currency, billing_interval=lease.billing_interval, billing_unit=lease.billing_unit, billing_strategy=lease.billing_strategy,
        billing_day=lease.billing_day, security_deposit=deposit, status=Lease.Status.ACTIVE, unit_rate=lease.unit_rate,
        unit_type_rate=lease.unit_type_rate, property_rate=lease.property_rate, is_custom_price=lease.is_custom_price)
    renewed.tenants.set(lease.tenants.all()); generate_rent_schedule(renewed)
    return renewed


@transaction.atomic
def settle_deposit(lease, *, refund_amount, deductions, status="settled", settlement_date=None, refund_reference="", notes=""):
    lease = Lease.objects.select_for_update().get(pk=lease.pk)
    if lease.status != Lease.Status.TERMINATED: raise ValidationError(_("Only terminated leases can have a deposit settlement."))
    if hasattr(lease, "deposit_settlement") and lease.deposit_settlement.status == DepositSettlement.Status.SETTLED: raise ValidationError(_("This deposit settlement is already settled."))
    original = lease.security_deposit; refund = Decimal(str(refund_amount or 0)); normalized = [(reason.strip(), Decimal(str(amount))) for reason, amount in deductions]
    if any(not reason for reason, _ in normalized): raise ValidationError(_("Every deduction requires a reason."))
    allocated = refund + sum((amount for _, amount in normalized), Decimal("0"))
    if allocated > original: raise ValidationError(_("Refund and deductions cannot exceed the original deposit."))
    if status == DepositSettlement.Status.SETTLED and allocated != original: raise ValidationError(_("A settled deposit must allocate the complete deposit."))
    settlement, _created = DepositSettlement.objects.update_or_create(lease=lease, defaults={"deposit_received": original, "original_amount": original, "currency": lease.currency, "refund_amount": refund, "status": status, "settlement_date": settlement_date or timezone.localdate(), "refund_reference": refund_reference, "notes": notes, "settled_at": timezone.now() if status == "settled" else None})
    settlement.deductions.all().delete(); DepositDeduction.objects.bulk_create([DepositDeduction(settlement=settlement, description=reason, amount=amount) for reason, amount in normalized])
    if status == "settled": lease.deposit_refund_amount = refund; lease.deposit_refunded_at = timezone.now(); lease.save(update_fields=("deposit_refund_amount", "deposit_refunded_at", "updated_at"))
    return settlement


@transaction.atomic
def move_out_lease(lease, *, end_date, reason, notes="", settlement=None):
    lease = terminate_lease(lease, end_date=end_date, reason=reason, notes=notes)
    if settlement:
        settle_deposit(lease, **settlement)
    return lease
