from django.db import migrations, models
from django.utils import timezone


def backfill_applications(apps, schema_editor):
    Application = apps.get_model("portal", "Application")
    UnitRate = apps.get_model("properties", "UnitRate")
    UnitTypeRate = apps.get_model("properties", "UnitTypeRate")
    PropertyRate = apps.get_model("properties", "PropertyRate")
    today = timezone.localdate()
    claimed_keys = set()

    def active_rates(queryset):
        return queryset.filter(is_active=True, starts_on__lte=today).filter(
            models.Q(ends_on__isnull=True) | models.Q(ends_on__gte=today)
        ).order_by("amount", "pk")

    for application in Application.objects.select_related("unit").order_by("submitted_at", "pk"):
        application.status = {
            "draft": "new",
            "submitted": "new",
            "approved": "accepted",
        }.get(application.status, application.status)
        unit_type_id = application.unit.unit_type_id if application.unit_id else None
        application.unit_type_id = unit_type_id
        application.target_type = "unit_type" if unit_type_id else "whole_property"

        rate = None
        if application.unit_id:
            rate = active_rates(UnitRate.objects.filter(unit_id=application.unit_id)).first()
        if rate is None and unit_type_id:
            rate = active_rates(UnitTypeRate.objects.filter(unit_type_id=unit_type_id)).first()
        if rate is None and not unit_type_id:
            rate = active_rates(PropertyRate.objects.filter(property_id=application.property_id)).first()
        if rate is not None:
            application.rental_billing_unit = rate.billing_unit
            application.rental_billing_interval = rate.billing_interval
            application.rental_currency = rate.currency
            application.rental_amount = rate.amount
        elif application.unit_id and application.unit.monthly_rent is not None:
            application.rental_billing_unit = "month"
            application.rental_billing_interval = 1
            application.rental_currency = "OMR"
            application.rental_amount = application.unit.monthly_rent

        if application.status in {"new", "reviewing"}:
            target = str(unit_type_id) if unit_type_id else "property"
            key = f"email:{application.email.strip().lower()}|{application.target_type}|{application.property_id}|{target}"
            if key in claimed_keys:
                application.status = "rejected"
            else:
                application.open_application_key = key
                claimed_keys.add(key)
        application.save()


class Migration(migrations.Migration):
    dependencies = [("portal", "0002_application_applicant_feedback_and_more")]

    operations = [
        migrations.RunPython(backfill_applications, migrations.RunPython.noop),
    ]
