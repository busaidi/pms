import django.utils.timezone
from django.db import migrations


def migrate_phase6_data(apps, schema_editor):
    Ticket = apps.get_model("operations", "MaintenanceTicket")
    History = apps.get_model("operations", "MaintenanceStatusHistory")
    ReminderSettings = apps.get_model("operations", "ReminderSettings")
    Ticket.objects.filter(priority="normal").update(priority="medium")
    for old, new in {"open": "reported", "assigned": "in_progress", "closed": "resolved"}.items():
        Ticket.objects.filter(status=old).update(status=new)
    year = django.utils.timezone.localdate().year
    for number, ticket in enumerate(Ticket.objects.order_by("id"), start=1):
        updates = []
        if not ticket.reference:
            ticket.reference = f"TKT{year}{number:04d}"
            updates.append("reference")
        if ticket.status == "resolved" and not ticket.resolution_notes:
            ticket.resolution_notes = "Resolved before maintenance history tracking was enabled."
            updates.append("resolution_notes")
        if updates:
            ticket.save(update_fields=updates)
        History.objects.get_or_create(ticket=ticket, to_status=ticket.status, defaults={"notes": "Imported from the existing maintenance register."})
    ReminderSettings.objects.get_or_create(pk=1, defaults={"overdue_intervals": [1, 3, 7], "channels": ["database", "log"]})


class Migration(migrations.Migration):
    dependencies = [("operations", "0002_remindersettings_maintenanceattachment_mime_type_and_more")]
    operations = [migrations.RunPython(migrate_phase6_data, migrations.RunPython.noop)]
