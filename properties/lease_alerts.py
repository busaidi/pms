"""Live operator alerts; no worker or outbound messages are required."""
from datetime import timedelta

from django.utils import timezone

from accounts.access import properties_for_user
from .models import Lease


def lease_alerts_for(user, days=30):
    today = timezone.localdate()
    return Lease.objects.filter(
        property__in=properties_for_user(user, "leases.view"),
        status=Lease.Status.ACTIVE,
        archived_at__isnull=True,
        end_date__lte=today + timedelta(days=days),
    ).select_related("property", "unit", "primary_tenant").order_by("end_date", "pk")
