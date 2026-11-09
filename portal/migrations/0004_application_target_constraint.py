from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("portal", "0003_backfill_application_offers")]

    operations = [
        migrations.AddConstraint(
            model_name="application",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(target_type="whole_property", unit_type__isnull=True)
                    | models.Q(target_type="unit_type", unit_type__isnull=False)
                ),
                name="application_target_matches_unit_type",
            ),
        ),
    ]
