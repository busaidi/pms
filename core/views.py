from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.db import connection
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone, translation
from django.views.i18n import set_language
from redis import Redis

from billing.models import Invoice, Payment
from operations.models import Expense, MaintenanceTicket
from properties.models import Lease, Property, Tenant, Unit
from accounts.access import properties_for_user, user_has_capability
from operations.models import ReminderLog
from operations.reports import financial_report


def set_language_preference(request):
    """Use Django's safe language cookie and remember authenticated preferences."""
    response = set_language(request)
    language = request.POST.get("language", "")
    if request.method == "POST" and request.user.is_authenticated:
        try:
            language = translation.get_supported_language_variant(language)
        except LookupError:
            language = ""
        if language in dict(settings.LANGUAGES):
            from accounts.models import UserProfile

            UserProfile.objects.update_or_create(
                user=request.user,
                defaults={"preferred_language": language},
            )
    return response


def health(request):
    checks = {"database": False, "redis": False}
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            checks["database"] = cursor.fetchone() == (1,)
    except Exception:
        pass
    try:
        checks["redis"] = bool(Redis.from_url(settings.CELERY_BROKER_URL, socket_timeout=1).ping())
    except Exception:
        pass
    healthy = all(checks.values())
    return JsonResponse({"status": "ok" if healthy else "degraded", "checks": checks}, status=200 if healthy else 503)


@login_required
def dashboard(request):
    property_scope = properties_for_user(request.user, "dashboard.view")
    if not user_has_capability(request.user, "dashboard.view") and not property_scope.exists():
        from portal.selectors import has_portal_identity
        if has_portal_identity(request.user):
            from django.shortcuts import redirect
            return redirect("portal_dashboard")
        raise PermissionDenied
    units = Unit.objects.filter(property__in=property_scope).select_related("property")
    total_units = units.count()
    occupied_units = units.filter(status=Unit.Status.OCCUPIED).count()
    available_units = units.filter(status=Unit.Status.AVAILABLE).count()
    maintenance_units = units.filter(status=Unit.Status.MAINTENANCE).count()
    occupancy = round((occupied_units / total_units) * 100) if total_units else 0
    monthly_rent = (
        Lease.objects.filter(property__in=property_scope, status=Lease.Status.ACTIVE).aggregate(
            total=Sum("monthly_rent")
        )["total"]
        or Decimal("0")
    )
    overdue_total = (
        Invoice.objects.filter(lease__property__in=property_scope, status=Invoice.Status.OVERDUE).aggregate(total=Sum("total"))["total"]
        or Decimal("0")
    )

    open_maintenance = MaintenanceTicket.objects.filter(property__in=property_scope).exclude(
        status=MaintenanceTicket.Status.RESOLVED
    ).count()
    collected_total = (
        Payment.objects.filter(invoice__lease__property__in=property_scope, status=Payment.Status.CONFIRMED).aggregate(total=Sum("amount"))["total"]
        or Decimal("0")
    )
    expense_total = Expense.objects.filter(property__in=property_scope).aggregate(total=Sum("amount"))["total"] or Decimal("0")
    properties = property_scope.annotate(
        unit_total=Count("units"),
        occupied_total=Count("units", filter=Q(units__status=Unit.Status.OCCUPIED)),
    ).order_by("name")[:5]
    recent_leases = Lease.objects.filter(property__in=property_scope).select_related("tenant", "unit", "property")[:5]

    return render(
        request,
        "core/dashboard.html",
        {
            "total_units": total_units,
            "occupied_units": occupied_units,
            "available_units": available_units,
            "maintenance_units": maintenance_units,
            "occupancy": occupancy,
            "monthly_rent": monthly_rent,
            "overdue_total": overdue_total,
            "open_maintenance": open_maintenance,
            "collected_total": collected_total,
            "expense_total": expense_total,
            "property_count": property_scope.filter(is_active=True).count(),
            "tenant_count": Tenant.objects.filter(is_active=True, leases__property__in=property_scope).distinct().count(),
            "properties": properties,
            "recent_leases": recent_leases,
        },
    )


@login_required
def global_search(request):
    query = request.GET.get("q", "").strip()
    results = {"properties": [], "units": [], "tenants": [], "leases": [], "invoices": []}
    if query:
        property_scope = properties_for_user(request.user, "properties.view")
        tenant_scope = properties_for_user(request.user, "tenants.view")
        lease_scope = properties_for_user(request.user, "leases.view")
        financial_scope = properties_for_user(request.user, "financials.view")
        if property_scope.exists():
            results["properties"] = property_scope.filter(Q(name__icontains=query) | Q(address__icontains=query))[:10]
            results["units"] = Unit.objects.filter(property__in=property_scope).filter(Q(name__icontains=query) | Q(property__name__icontains=query)).select_related("property")[:10]
        if tenant_scope.exists():
            results["tenants"] = Tenant.objects.filter(Q(leases__property__in=tenant_scope) | Q(created_by=request.user)).filter(Q(full_name__icontains=query) | Q(email__icontains=query) | Q(phone__icontains=query) | Q(id_number__icontains=query)).distinct()[:10]
        if lease_scope.exists():
            results["leases"] = Lease.objects.filter(property__in=lease_scope).filter(Q(reference__icontains=query) | Q(tenant__full_name__icontains=query) | Q(unit__name__icontains=query)).select_related("property", "unit", "tenant")[:10]
        if financial_scope.exists():
            results["invoices"] = Invoice.objects.filter(lease__property__in=financial_scope).filter(Q(number__icontains=query) | Q(lease__tenant__full_name__icontains=query)).select_related("lease__tenant", "lease__property")[:10]
    return render(request, "core/search.html", {"query": query, "results": results})


@login_required
def financial_dashboard(request):
    if not user_has_capability(request.user, "financials.view"):
        raise PermissionDenied
    properties = properties_for_user(request.user, "financials.view")
    selected = request.GET.get("property", "")
    if selected and not properties.filter(pk=selected).exists():
        raise PermissionDenied
    period = request.GET.get("period", "current_month")
    if period not in {"current_month", "ytd"}:
        period = "current_month"
    currency = request.GET.get("currency", "").upper()
    report = financial_report(properties, period=period, property_id=selected or None, currency=currency)
    return render(request, "core/financial_dashboard.html", {"report": report, "properties": properties.order_by("name"), "selected_property": selected, "period": period, "currency": currency})


@login_required
def rent_dashboard(request):
    if not (user_has_capability(request.user, "dashboard.view") or user_has_capability(request.user, "financials.view")):
        raise PermissionDenied
    today = timezone.localdate()
    properties = properties_for_user(request.user, "leases.view")
    invoices = Invoice.objects.filter(lease__property__in=properties).exclude(status__in=(Invoice.Status.VOID, Invoice.Status.CANCELLED)).select_related("lease__property", "lease__unit", "lease__primary_tenant")
    urgency = request.GET.get("urgency", "all")
    if urgency == "overdue":
        invoices = invoices.exclude(status=Invoice.Status.PAID).filter(due_date__lt=today)
    elif urgency == "due_today":
        invoices = invoices.exclude(status=Invoice.Status.PAID).filter(due_date=today)
    elif urgency == "upcoming":
        invoices = invoices.exclude(status=Invoice.Status.PAID).filter(due_date__gt=today, due_date__lte=today + timedelta(days=7))
    elif urgency == "paid":
        invoices = invoices.filter(status=Invoice.Status.PAID)
    else:
        invoices = invoices.exclude(status=Invoice.Status.PAID)
    all_invoices = Invoice.objects.filter(lease__property__in=properties).exclude(status__in=(Invoice.Status.VOID, Invoice.Status.CANCELLED))
    totals = {}
    for invoice in all_invoices.exclude(status=Invoice.Status.PAID):
        totals[invoice.currency] = totals.get(invoice.currency, Decimal("0")) + invoice.balance
    counts = {"all": all_invoices.exclude(status=Invoice.Status.PAID).count(), "overdue": all_invoices.exclude(status=Invoice.Status.PAID).filter(due_date__lt=today).count(), "due_today": all_invoices.exclude(status=Invoice.Status.PAID).filter(due_date=today).count(), "upcoming": all_invoices.exclude(status=Invoice.Status.PAID).filter(due_date__gt=today, due_date__lte=today + timedelta(days=7)).count(), "paid": all_invoices.filter(status=Invoice.Status.PAID).count()}
    recent_payments = Payment.objects.filter(invoice__lease__property__in=properties, status=Payment.Status.CONFIRMED).select_related("invoice", "tenant")[:8]
    invoice_ids = [str(value) for value in all_invoices.values_list("pk", flat=True)]
    recent_reminders = ReminderLog.objects.filter(subject_type="billing.Invoice", subject_id__in=invoice_ids)[:8]
    return render(request, "core/rent_dashboard.html", {"invoices": Paginator(invoices, 25).get_page(request.GET.get("page")), "urgency": urgency, "counts": counts, "outstanding": sorted(totals.items()), "recent_payments": recent_payments, "recent_reminders": recent_reminders, "today": today})

# Create your views here.
