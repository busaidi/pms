from collections import OrderedDict
from datetime import date

from django.db.models import Q

from .models import PropertyRate, UnitRate, UnitTypeRate


def current_rates(queryset, on_date=None):
    on_date = on_date or date.today()
    return queryset.filter(is_active=True, starts_on__lte=on_date).filter(
        Q(ends_on__isnull=True) | Q(ends_on__gte=on_date)
    ).order_by("billing_unit", "billing_interval", "currency", "-starts_on", "-pk")


def effective_unit_rates(unit, on_date=None):
    """Resolve one current rate per period/currency; unit prices win over type prices."""
    resolved = OrderedDict()
    if unit.unit_type_id:
        for rate in current_rates(UnitTypeRate.objects.filter(unit_type_id=unit.unit_type_id), on_date):
            key = (rate.billing_interval, rate.billing_unit, rate.currency)
            resolved.setdefault(key, {"rate": rate, "source": "unit type"})
    unit_keys = set()
    for rate in current_rates(UnitRate.objects.filter(unit=unit), on_date):
        key = (rate.billing_interval, rate.billing_unit, rate.currency)
        if key not in unit_keys:
            resolved[key] = {"rate": rate, "source": "unit"}
            unit_keys.add(key)
    return sorted(resolved.values(), key=lambda item: (
        {"day": 1, "week": 2, "month": 3, "year": 4}[item["rate"].billing_unit],
        item["rate"].billing_interval,
        item["rate"].currency,
    ))


def publication_readiness(property_obj):
    problems = []
    if property_obj.archived_at or not property_obj.is_active:
        problems.append("Restore and activate this property.")
    if not property_obj.description.strip():
        problems.append("Add a property description.")
    if not property_obj.public_slug:
        problems.append("Add a public listing slug.")
    whole_ready = property_obj.supports_property_pricing and current_rates(
        PropertyRate.objects.filter(property=property_obj)
    ).exists()
    unit_ready = False
    if property_obj.supports_unit_inventory:
        units = property_obj.units.filter(archived_at__isnull=True).exclude(status__in=("maintenance", "unavailable"))
        unit_ready = any(effective_unit_rates(unit) for unit in units.select_related("unit_type"))
    if not (whole_ready or unit_ready):
        problems.append("Add an active current rate to an eligible offering.")
    if property_obj.supports_unit_inventory and not property_obj.unit_types.filter(archived_at__isnull=True, is_active=True).exists():
        problems.append("Add an active unit type.")
    return {"ready": not problems, "problems": problems, "whole_ready": whole_ready, "unit_ready": unit_ready}
