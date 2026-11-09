from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from properties.models import Tenant
from properties.services import current_rates, effective_unit_rates, publication_readiness

from .models import Application
from django.utils.translation import gettext_lazy as _


APPLICATION_TRANSITIONS = {
    Application.Status.NEW: {Application.Status.REVIEWING, Application.Status.WITHDRAWN},
    Application.Status.REVIEWING: {Application.Status.ACCEPTED, Application.Status.REJECTED, Application.Status.WITHDRAWN},
    Application.Status.ACCEPTED: set(), Application.Status.REJECTED: set(), Application.Status.WITHDRAWN: set(),
}


def public_properties():
    from properties.models import Property
    candidates = Property.objects.filter(is_public=True, is_published=True, is_active=True, archived_at__isnull=True).prefetch_related("amenities", "units__unit_type", "rates", "unit_types__rates", "units__rates")
    return [item for item in candidates if publication_readiness(item)["ready"]]


def public_property(slug):
    return next((item for item in public_properties() if item.public_slug == slug or item.slug == slug), None)


def resolve_offer(property_obj, unit_type=None):
    from properties.lease_services import active_leases
    blockers = active_leases().filter(property=property_obj)
    if unit_type is None:
        if blockers.exists():
            return None
        rate = current_rates(property_obj.rates.all()).first()
    else:
        if blockers.filter(unit__isnull=True).exists():
            return None
        rates = []
        for unit in unit_type.units.filter(status="available", archived_at__isnull=True).exclude(pk__in=blockers.values("unit_id")):
            rates.extend(item["rate"] for item in effective_unit_rates(unit))
        rate = sorted(rates, key=lambda item: (item.amount, item.currency))[0] if rates else None
    if not rate: return None
    return {"rental_billing_unit": rate.billing_unit, "rental_billing_interval": rate.billing_interval, "rental_currency": rate.currency, "rental_amount": rate.amount}


@transaction.atomic
def submit_application(*, user=None, property_obj, unit_type=None, unit=None, **data):
    target_type = Application.TargetType.UNIT_TYPE if unit_type else Application.TargetType.WHOLE_PROPERTY
    offer = resolve_offer(property_obj, unit_type)
    if not offer: raise ValidationError(_("This rental offering has no active price."))
    identity = f"user:{user.pk}" if user and user.is_authenticated else f"email:{data['email'].strip().lower()}"
    key = f"{identity}|{target_type}|{property_obj.pk}|{unit_type.pk if unit_type else 'property'}"
    if Application.objects.select_for_update().filter(open_application_key=key).exists(): raise ValidationError(_("You already have an open application for this offering."))
    return Application.objects.create(user=user if user and user.is_authenticated else None, property=property_obj, unit=unit, unit_type=unit_type, target_type=target_type, open_application_key=key, status=Application.Status.NEW, **offer, **data)


@transaction.atomic
def transition_application(application, status, *, actor, operator_notes="", applicant_feedback="", applicant=False):
    application = Application.objects.select_for_update().get(pk=application.pk)
    if status not in APPLICATION_TRANSITIONS.get(application.status, set()): raise ValidationError(_("That application status transition is not allowed."))
    if applicant and status != Application.Status.WITHDRAWN: raise ValidationError(_("Applicants may only withdraw an application."))
    application.status = status
    if not application.is_open: application.open_application_key = None
    if not applicant:
        application.operator_notes = operator_notes; application.applicant_feedback = applicant_feedback; application.reviewed_by = actor; application.reviewed_at = timezone.now()
    application.save()
    return application


@transaction.atomic
def convert_application(application, *, actor):
    application = Application.objects.select_for_update().get(pk=application.pk)
    if application.status != Application.Status.ACCEPTED: raise ValidationError(_("Only accepted applications can be converted."))
    if application.converted_tenant_id: return application.converted_tenant
    tenant = Tenant.objects.filter(user=application.user).first() if application.user_id else None
    if tenant and (tenant.archived_at or not tenant.is_active): raise ValidationError(_("The linked tenant record is archived or inactive."))
    tenant = tenant or Tenant.objects.create(user=application.user, full_name=application.full_name, email=application.email, phone=application.phone, nationality=application.nationality, created_by=actor, portal_enabled=bool(application.user_id))
    application.converted_tenant = tenant; application.converted_at = timezone.now(); application.save(update_fields=("converted_tenant", "converted_at", "updated_at")); return tenant
