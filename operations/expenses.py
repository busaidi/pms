import calendar
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import Expense, RecurringExpense
from django.utils.translation import gettext_lazy as _


def _add_months(value, months):
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    return value.replace(year=year, month=month, day=min(value.day, calendar.monthrange(year, month)[1]))


def next_occurrence(schedule, current):
    interval = max(schedule.billing_interval, 1)
    if schedule.billing_unit == RecurringExpense.BillingUnit.DAY:
        return current + timedelta(days=interval)
    if schedule.billing_unit == RecurringExpense.BillingUnit.WEEK:
        return current + timedelta(weeks=interval)
    if schedule.billing_unit == RecurringExpense.BillingUnit.MONTH:
        return _add_months(current, interval)
    return _add_months(current, 12 * interval)


@transaction.atomic
def record_expense(*, actor, receipt=None, **data):
    expense = Expense(**data, created_by=actor)
    if receipt:
        expense.receipt = receipt
        expense.receipt_original_name = receipt.name
        expense.receipt_mime_type = getattr(receipt, "content_type", "")
        expense.receipt_size = receipt.size
    expense.full_clean()
    expense.save()
    return expense


@transaction.atomic
def update_expense(expense, *, receipt=None, **data):
    expense = Expense.objects.select_for_update().get(pk=expense.pk)
    if expense.status == Expense.Status.VOIDED:
        raise ValidationError(_("Voided expenses are immutable."))
    if "currency" in data and data["currency"].upper() != expense.currency:
        raise ValidationError(_("The expense currency snapshot cannot change."))
    for field, value in data.items():
        setattr(expense, field, value)
    if receipt:
        expense.receipt = receipt
        expense.receipt_original_name = receipt.name
        expense.receipt_mime_type = getattr(receipt, "content_type", "")
        expense.receipt_size = receipt.size
    expense.full_clean(); expense.save()
    return expense


@transaction.atomic
def void_expense(expense, *, actor, reason):
    expense = Expense.objects.select_for_update().get(pk=expense.pk)
    if expense.status == Expense.Status.VOIDED:
        return expense
    if not reason.strip():
        raise ValidationError(_("A reason is required to void an expense."))
    expense.status = Expense.Status.VOIDED
    expense.void_reason = reason.strip()
    expense.voided_at = timezone.now()
    expense.voided_by = actor
    expense.full_clean(); expense.save()
    return expense


@transaction.atomic
def create_recurring_expense(*, actor, **data):
    schedule = RecurringExpense(**data, created_by=actor, next_run_on=data["start_date"], is_active=True, is_paused=False)
    schedule.full_clean(); schedule.save()
    return schedule


@transaction.atomic
def generate_recurring_expenses(today=None, actor=None):
    today = today or timezone.localdate()
    created = 0
    schedules = (
        RecurringExpense.objects.select_for_update(of=("self",))
        .filter(is_active=True, is_paused=False, next_run_on__lte=today)
        .select_related("property", "category")
    )
    for schedule in schedules:
        while schedule.next_run_on and schedule.next_run_on <= today:
            due = schedule.next_run_on
            if schedule.ends_on and due > schedule.ends_on:
                schedule.next_run_on = None
                schedule.is_active = False
                break
            _, was_created = Expense.objects.get_or_create(
                recurring_expense=schedule,
                incurred_on=due,
                defaults={"property": schedule.property, "category": schedule.category, "amount": schedule.amount, "currency": schedule.currency, "vendor": schedule.vendor, "description": schedule.description, "notes": schedule.notes, "created_by": actor or schedule.created_by},
            )
            created += int(was_created)
            following = next_occurrence(schedule, due)
            schedule.next_run_on = None if schedule.ends_on and following > schedule.ends_on else following
            if schedule.next_run_on is None:
                schedule.is_active = False
        schedule.save(update_fields=("next_run_on", "is_active", "updated_at"))
    return created


@transaction.atomic
def set_schedule_paused(schedule, paused):
    schedule = RecurringExpense.objects.select_for_update().get(pk=schedule.pk)
    if paused:
        schedule.is_active = False; schedule.is_paused = True; schedule.paused_at = timezone.now()
    else:
        next_due = schedule.next_run_on or schedule.start_date
        today = timezone.localdate()
        while next_due <= today:
            next_due = next_occurrence(schedule, next_due)
        if schedule.ends_on and next_due > schedule.ends_on:
            raise ValidationError(_("This schedule has no future occurrence."))
        schedule.next_run_on = next_due; schedule.is_active = True; schedule.is_paused = False; schedule.paused_at = None
    schedule.save()
    return schedule
