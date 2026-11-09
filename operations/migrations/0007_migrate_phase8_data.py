from django.db import migrations, models


def migrate_phase8_data(apps, schema_editor):
    Meter = apps.get_model("operations", "UtilityMeter")
    Reading = apps.get_model("operations", "UtilityReading")
    Inspection = apps.get_model("operations", "Inspection")
    Photo = apps.get_model("operations", "InspectionPhoto")
    for meter in Meter.objects.all():
        latest = meter.readings.order_by("-read_at").first()
        if latest:
            meter.rate = latest.rate
        meter.currency = "OMR"
        meter.save(update_fields=("rate", "currency"))
    for number, reading in enumerate(Reading.objects.order_by("meter_id", "read_at", "id"), start=1):
        reading.reading_date = reading.read_at.date()
        reading.period_start = reading.read_at.date()
        reading.period_end = reading.read_at.date()
        reading.current_reading = reading.value
        reading.consumption = reading.value - (reading.previous_value or 0)
        reading.currency = "OMR"
        reading.reference = f"UTLLEGACY{number:05d}"
        reading.reading_kind = "adjustment" if reading.is_correction else "reading"
        reading.adjustment_consumption = reading.consumption if reading.is_correction else 0
        reading.save(update_fields=("reading_date", "period_start", "period_end", "current_reading", "consumption", "currency", "reference", "reading_kind", "adjustment_consumption"))
    for inspection in Inspection.objects.select_related("unit", "lease", "template"):
        inspection.property_id = inspection.unit.property_id if inspection.unit_id else inspection.lease.property_id if inspection.lease_id else None
        inspection.template_name = inspection.template.name
        inspection.inspection_type = inspection.template.inspection_type
        inspection.inspection_date = inspection.scheduled_for.date()
        if inspection.status in {"scheduled", "in_progress"}:
            inspection.status = "draft"
        inspection.save(update_fields=("property", "template_name", "inspection_type", "inspection_date", "status"))
    for photo in Photo.objects.all():
        photo.original_name = photo.file.name.rsplit("/", 1)[-1]
        photo.save(update_fields=("original_name",))


class Migration(migrations.Migration):
    dependencies = [("operations", "0006_alter_utilityreading_options_inspection_completed_by_and_more")]
    operations = [
        migrations.RunPython(migrate_phase8_data, migrations.RunPython.noop),
        migrations.AddConstraint(model_name="utilityreading", constraint=models.UniqueConstraint(condition=models.Q(reading_kind="reading"), fields=("meter", "reading_date", "reading_kind"), name="unique_meter_reading_date")),
    ]
