import os

from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("pms")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
app.conf.beat_schedule = {
    "generate-rent-invoices": {"task": "core.tasks.generate_rent_invoices", "schedule": crontab(hour=1, minute=0)},
    "generate-recurring-expenses": {"task": "core.tasks.generate_recurring_expenses", "schedule": crontab(hour=1, minute=5)},
    "reconcile-payment-attempts": {"task": "core.tasks.reconcile_payment_attempts", "schedule": crontab(minute="*/5")},
    "send-rent-reminders": {"task": "core.tasks.send_rent_reminders", "schedule": crontab(hour=8, minute=0)},
    "send-lease-expiration-notices": {"task": "core.tasks.send_lease_expiration_notices", "schedule": crontab(hour=8, minute=5)},
}
