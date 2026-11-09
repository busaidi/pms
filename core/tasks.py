from datetime import timedelta
from decimal import Decimal

from celery import shared_task
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from billing.gateways import reconcile_attempt
from billing.models import Invoice, PaymentAttempt
from billing.services import ensure_invoice_pdf, generate_invoices
from operations.expenses import generate_recurring_expenses as generate_recurring_expense_rows
from operations.services import send_due_rent_reminders, send_expiration_notices


@shared_task
def generate_rent_invoices():
    return len(generate_invoices())


@shared_task
def generate_recurring_expenses():
    actor = get_user_model().objects.filter(is_superuser=True).order_by("id").first()
    if actor is None:
        return 0
    return generate_recurring_expense_rows(actor=actor)


@shared_task
def reconcile_payment_attempts():
    count = 0
    for attempt in PaymentAttempt.objects.filter(status=PaymentAttempt.Status.PENDING).iterator():
        before = attempt.status; after = reconcile_attempt(attempt)
        count += int(after.status != before)
    return count


@shared_task
def generate_invoice_pdf_artifact(invoice_id):
    return ensure_invoice_pdf(Invoice.objects.get(pk=invoice_id)).pk


@shared_task
def send_rent_reminders():
    return send_due_rent_reminders()


@shared_task
def send_lease_expiration_notices():
    return send_expiration_notices()
