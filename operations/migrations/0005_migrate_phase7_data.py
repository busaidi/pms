from django.db import migrations
from django.utils.text import slugify


def migrate_phase7_data(apps, schema_editor):
    Category = apps.get_model("operations", "ExpenseCategory")
    Recurring = apps.get_model("operations", "RecurringExpense")
    for category in Category.objects.order_by("id"):
        base = slugify(category.name) or f"category-{category.pk}"
        candidate = base
        suffix = 2
        while Category.objects.exclude(pk=category.pk).filter(slug=candidate).exists():
            candidate = f"{base}-{suffix}"
            suffix += 1
        category.slug = candidate
        category.save(update_fields=("slug",))
    mapping = {"daily": (1, "day"), "weekly": (1, "week"), "monthly": (1, "month"), "quarterly": (3, "month"), "yearly": (1, "year")}
    for schedule in Recurring.objects.all():
        interval, unit = mapping.get(schedule.frequency, (1, "month"))
        schedule.billing_interval = interval
        schedule.billing_unit = unit
        schedule.start_date = schedule.next_run_on
        schedule.is_active = not schedule.is_paused
        schedule.save(update_fields=("billing_interval", "billing_unit", "start_date", "is_active"))


class Migration(migrations.Migration):
    dependencies = [("operations", "0004_alter_expensecategory_options_expense_currency_and_more")]
    operations = [migrations.RunPython(migrate_phase7_data, migrations.RunPython.noop)]
