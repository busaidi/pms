from collections import defaultdict
from datetime import date
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone

from billing.models import Invoice, PaymentAllocation
from properties.models import Property, Unit

from .models import Expense


def _groups(rows):
    values = defaultdict(lambda: Decimal("0"))
    for currency, amount in rows:
        values[currency] += amount or Decimal("0")
    return [{"currency": currency, "amount": amount} for currency, amount in sorted(values.items())]


def _subtract(left, right):
    values = defaultdict(lambda: Decimal("0"))
    for item in left: values[item["currency"]] += item["amount"]
    for item in right: values[item["currency"]] -= item["amount"]
    return [{"currency": key, "amount": value} for key, value in sorted(values.items())]


def financial_report(properties, *, period="current_month", property_id=None, currency="", today=None):
    today = today or timezone.localdate()
    start = date(today.year, 1, 1) if period == "ytd" else today.replace(day=1)
    if property_id:
        properties = properties.filter(pk=property_id)
    invoices = Invoice.objects.filter(lease__property__in=properties, issue_date__range=(start, today)).exclude(status__in=(Invoice.Status.VOID, Invoice.Status.CANCELLED))
    expenses = Expense.objects.filter(property__in=properties, incurred_on__range=(start, today), status=Expense.Status.ACTIVE)
    if currency:
        invoices = invoices.filter(currency=currency); expenses = expenses.filter(currency=currency)
    revenue = _groups(invoices.values_list("currency").annotate(value=Sum("total")).values_list("currency", "value"))
    expense_groups = _groups(expenses.values_list("currency").annotate(value=Sum("amount")).values_list("currency", "value"))
    allocations = PaymentAllocation.objects.filter(invoice__in=invoices, payment__status="confirmed")
    collected = _groups(allocations.values_list("invoice__currency").annotate(value=Sum("amount")).values_list("invoice__currency", "value"))
    outstanding_rows = []
    for invoice in invoices:
        outstanding_rows.append((invoice.currency, invoice.balance))
    outstanding = _groups(outstanding_rows)
    noi = _subtract(revenue, expense_groups)
    by_property = []
    for property_obj in properties.order_by("name"):
        property_invoices = invoices.filter(lease__property=property_obj)
        billed = property_invoices.aggregate(value=Sum("total"))["value"] or Decimal("0")
        costs = expenses.filter(property=property_obj).aggregate(value=Sum("amount"))["value"] or Decimal("0")
        by_property.append({"property": property_obj, "revenue": billed, "expenses": costs, "noi": billed - costs})
    total_units = Unit.objects.filter(property__in=properties).count()
    occupied = Unit.objects.filter(property__in=properties, status=Unit.Status.OCCUPIED).count()
    return {"period": period, "start": start, "end": today, "revenue": revenue, "expenses": expense_groups, "noi": noi, "collected": collected, "outstanding": outstanding, "properties": by_property, "occupancy": round(occupied * 100 / total_units, 1) if total_units else 0}
