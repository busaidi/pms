from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.access import properties_for_user, user_has_capability
from accounts.models import AppSetting
from properties.models import PropertyMedia, UnitType
from properties.services import current_rates, effective_unit_rates

from .forms import ApplicationForm, ApplicationReviewForm, PublicPortalSettingsForm
from .models import Application
from .services import convert_application, public_properties, public_property, submit_application, transition_application
from django.utils.translation import gettext_lazy as _


def _setting(key, default):
    setting = AppSetting.objects.filter(key=key).first()
    return setting.get_value(default) if setting else default


def _metadata(request, title, description, image=""):
    return {"seo_title": title, "seo_description": description, "seo_canonical": request.build_absolute_uri(request.path), "seo_image": image or _setting("public.social_image_url", ""), "public_site_name": _setting("public.site_name", "Oman Skylight"), "public_logo_url": _setting("public.logo_url", ""), "public_favicon_url": _setting("public.favicon_url", "")}


def listing_index(request):
    properties = public_properties()
    return render(request, "portal/listing_index.html", {"properties": properties, **_metadata(request, _setting("public.homepage_title", "Homes in Oman · Oman Skylight"), _setting("public.homepage_description", "Professionally managed homes across Oman."))})


def listing_detail(request, slug):
    property_obj = public_property(slug)
    if property_obj is None: raise Http404
    available_units = property_obj.units.filter(status="available", archived_at__isnull=True, unit_type__is_published=True).select_related("unit_type").order_by("monthly_rent")
    gallery_media = property_obj.media.filter(is_public=True, kind=PropertyMedia.Kind.IMAGE, unit_type__isnull=True)
    return render(request, "portal/listing_detail.html", {"property": property_obj, "available_units": available_units, "gallery_media": gallery_media, **_metadata(request, f"{property_obj.name} · {_setting('public.site_name', 'Oman Skylight')}", property_obj.description or f"Homes at {property_obj.name} in {property_obj.city}.")})


def apply(request, slug):
    property_obj = public_property(slug)
    if property_obj is None: raise Http404
    available_units = property_obj.units.filter(status="available", archived_at__isnull=True, unit_type__is_published=True).select_related("unit_type").order_by("name")
    unit_type_slug = request.POST.get("unit_type") or request.GET.get("unit_type")
    unit_id = request.POST.get("unit") if request.method == "POST" else request.GET.get("unit")
    selected_unit = available_units.filter(pk=unit_id).first() if unit_id else None
    selected_type = selected_unit.unit_type if selected_unit else (property_obj.unit_types.filter(public_slug=unit_type_slug, is_active=True, is_published=True, archived_at__isnull=True).first() if unit_type_slug else None)
    form = ApplicationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            submit_application(user=request.user, property_obj=property_obj, unit_type=selected_type, unit=selected_unit, **form.cleaned_data)
            messages.success(request, _("Your application has been received. Our team will contact you soon.")); return redirect("listing_detail", slug=slug)
        except ValidationError as error: form.add_error(None, error.messages[0])
    return render(request, "portal/application_form.html", {"property": property_obj, "available_units": available_units, "unit_types": property_obj.unit_types.filter(is_active=True, is_published=True), "selected_type": selected_type, "form": form, **_metadata(request, f"Apply for {property_obj.name}", f"Rental application for {property_obj.name}.")})


def unit_type_detail(request, slug, unit_type_slug):
    property_obj = public_property(slug)
    if property_obj is None: raise Http404
    unit_type = get_object_or_404(UnitType, property=property_obj, public_slug=unit_type_slug, is_active=True, is_published=True, archived_at__isnull=True)
    units = unit_type.units.filter(archived_at__isnull=True, status="available")
    rates = list(current_rates(unit_type.rates.all()))
    if not rates:
        seen = set()
        for unit in units.select_related("unit_type"):
            for item in effective_unit_rates(unit):
                rate = item["rate"]
                key = (rate.billing_interval, rate.billing_unit, rate.currency, rate.amount)
                if key not in seen:
                    rates.append(rate)
                    seen.add(key)
    if not units.exists() or not rates: raise Http404
    gallery_media = property_obj.media.filter(is_public=True, kind=PropertyMedia.Kind.IMAGE, unit_type=unit_type)
    return render(request, "portal/unit_type_detail.html", {"property": property_obj, "unit_type": unit_type, "available_units": units, "rates": rates, "gallery_media": gallery_media, **_metadata(request, f"{unit_type.name} at {property_obj.name}", unit_type.description or property_obj.description)})


def public_media(request, media_id):
    media = get_object_or_404(PropertyMedia, pk=media_id, is_public=True, property__is_public=True, property__is_published=True, property__is_active=True)
    if not media.file.storage.exists(media.file.name): raise Http404
    response = FileResponse(media.file.open("rb"), content_type="image/" + media.file.name.rsplit(".", 1)[-1].replace("jpg", "jpeg")); response["Cache-Control"] = "public, max-age=31536000, immutable"; return response


def _application_queryset(user):
    if user_has_capability(user, "tenants.view"): return Application.objects.all()
    return Application.objects.filter(property__in=properties_for_user(user, "tenants.view"))


@login_required
def application_list(request):
    if not (user_has_capability(request.user, "tenants.view") or properties_for_user(request.user, "tenants.view").exists()): raise PermissionDenied
    applications = _application_queryset(request.user).select_related("property", "unit_type", "assigned_to", "converted_tenant")
    status = request.GET.get("status", "")
    if status: applications = applications.filter(status=status)
    return render(request, "portal/application_list.html", {"applications": Paginator(applications, 25).get_page(request.GET.get("page")), "statuses": Application.Status.choices, "status": status})


@login_required
def application_workspace(request, application_id):
    application = get_object_or_404(_application_queryset(request.user).select_related("property", "unit", "unit_type", "assigned_to", "reviewed_by", "converted_tenant", "user"), pk=application_id)
    return render(request, "portal/application_workspace.html", {"application": application, "review_form": ApplicationReviewForm(initial={"status": application.status, "operator_notes": application.operator_notes, "applicant_feedback": application.applicant_feedback})})


@login_required
@require_POST
def application_transition(request, application_id):
    application = get_object_or_404(_application_queryset(request.user), pk=application_id); form = ApplicationReviewForm(request.POST)
    if form.is_valid():
        try: transition_application(application, actor=request.user, **form.cleaned_data); messages.success(request, _("Application status updated."))
        except ValidationError as error: messages.error(request, error.messages[0])
    return redirect("application_workspace", application_id=application.pk)


@login_required
@require_POST
def application_convert(request, application_id):
    if not user_has_capability(request.user, "tenants.create"): raise PermissionDenied
    application = get_object_or_404(_application_queryset(request.user), pk=application_id)
    try:
        tenant = convert_application(application, actor=request.user); messages.success(request, _("Converted to tenant %(tenant)s.") % {"tenant": tenant.full_name}); return redirect("tenant_workspace", tenant_id=tenant.pk)
    except ValidationError as error: messages.error(request, error.messages[0]); return redirect("application_workspace", application_id=application.pk)


@login_required
def public_portal_settings(request):
    if not user_has_capability(request.user, "roles.update"): raise PermissionDenied
    initial = {"site_name": _setting("public.site_name", "Oman Skylight"), "homepage_title": _setting("public.homepage_title", "Homes in Oman · Oman Skylight"), "homepage_description": _setting("public.homepage_description", "Professionally managed homes across Oman."), "social_image_url": _setting("public.social_image_url", ""), "logo_url": _setting("public.logo_url", ""), "favicon_url": _setting("public.favicon_url", "")}
    form = PublicPortalSettingsForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        for field, key in (("site_name", "public.site_name"), ("homepage_title", "public.homepage_title"), ("homepage_description", "public.homepage_description"), ("social_image_url", "public.social_image_url"), ("logo_url", "public.logo_url"), ("favicon_url", "public.favicon_url")):
            setting, _created = AppSetting.objects.get_or_create(key=key, defaults={"group": "public", "value_type": AppSetting.ValueType.STRING}); setting.set_value(form.cleaned_data[field]); setting.save()
        messages.success(request, _("Public portal settings saved.")); return redirect("public_portal_settings")
    return render(request, "properties/form.html", {"form": form, "title": "Public portal and SEO", "eyebrow": "Settings"})
