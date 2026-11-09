import logging
from dataclasses import dataclass

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone

from billing.models import Invoice
from integrations.services import send_whatsapp
from properties.models import Lease, Unit

from .models import MaintenanceAttachment, MaintenanceStatusHistory, MaintenanceTicket, ReminderLog, ReminderSettings, UserNotification
from django.utils.translation import gettext_lazy as _

logger = logging.getLogger(__name__)

ALLOWED_TRANSITIONS = {
    MaintenanceTicket.Status.REPORTED: {MaintenanceTicket.Status.IN_PROGRESS, MaintenanceTicket.Status.CANCELLED},
    MaintenanceTicket.Status.IN_PROGRESS: {MaintenanceTicket.Status.RESOLVED, MaintenanceTicket.Status.CANCELLED},
    MaintenanceTicket.Status.RESOLVED: set(),
    MaintenanceTicket.Status.CANCELLED: set(),
}


def _notify_user(user, *, kind, title, message, url="", payload=None):
    if user and user.is_active:
        return UserNotification.objects.create(recipient=user, kind=kind, title=title, message=message, url=url, payload=payload or {})


def _notify_ticket_people(ticket, kind, title, message):
    url = reverse("maintenance_workspace", kwargs={"ticket_id": ticket.pk})
    users = {user.pk: user for user in (ticket.tenant.user if ticket.tenant_id and ticket.tenant.user_id else None, ticket.assigned_to) if user}
    for user in users.values():
        _notify_user(user, kind=kind, title=title, message=message, url=url, payload={"ticket": ticket.reference})


@transaction.atomic
def create_ticket(*, actor, attachment=None, block_unit=False, **data):
    unit = None
    if data.get("unit"):
        unit = Unit.objects.select_for_update().get(pk=data["unit"].pk)
    ticket = MaintenanceTicket(**data, created_by=actor, blocks_unit=bool(block_unit and unit))
    ticket.full_clean()
    ticket.save()
    MaintenanceStatusHistory.objects.create(ticket=ticket, to_status=ticket.status, notes="Ticket reported.", actor=actor)
    if unit and block_unit:
        ticket.unit_status_before_block = unit.status
        ticket.save(update_fields=("unit_status_before_block", "updated_at"))
        if unit.status != Unit.Status.MAINTENANCE:
            unit.status = Unit.Status.MAINTENANCE
            unit.save(update_fields=("status", "updated_at"))
    if attachment:
        MaintenanceAttachment.objects.create(ticket=ticket, file=attachment, original_name=attachment.name, mime_type=getattr(attachment, "content_type", ""), size=attachment.size)
    _notify_ticket_people(ticket, "maintenance_created", "Maintenance request received", f"{ticket.reference}: {ticket.title}")
    return ticket


@transaction.atomic
def update_ticket(ticket, *, actor, **data):
    ticket = MaintenanceTicket.objects.select_for_update().get(pk=ticket.pk)
    changed = []
    for field, value in data.items():
        if getattr(ticket, field) != value:
            setattr(ticket, field, value)
            changed.append(field)
    if changed:
        ticket.full_clean()
        ticket.save(update_fields=tuple(changed) + ("updated_at",))
        _notify_ticket_people(ticket, "maintenance_updated", "Maintenance request updated", f"{ticket.reference} was updated.")
    return ticket


@transaction.atomic
def transition_ticket(ticket, new_status, *, actor, notes=""):
    ticket = (
        MaintenanceTicket.objects.select_for_update(of=("self",))
        .select_related("unit", "tenant__user", "assigned_to")
        .get(pk=ticket.pk)
    )
    old_status = ticket.status
    if new_status == old_status:
        return ticket
    if new_status not in ALLOWED_TRANSITIONS.get(old_status, set()):
        raise ValidationError(
            _("A %(status)s ticket cannot move to %(new_status)s.")
            % {
                "status": ticket.get_status_display().lower(),
                "new_status": dict(MaintenanceTicket.Status.choices).get(new_status, new_status),
            }
        )
    notes = notes.strip()
    if new_status == MaintenanceTicket.Status.RESOLVED:
        if not notes:
            raise ValidationError(_("Resolution notes are required."))
        ticket.resolution_notes = notes
        ticket.resolved_at = timezone.now()
        ticket.cost = ticket.actual_cost
    elif new_status == MaintenanceTicket.Status.CANCELLED:
        if not notes:
            raise ValidationError(_("A cancellation reason is required."))
        ticket.cancellation_reason = notes
        ticket.cancelled_at = timezone.now()
    ticket.status = new_status
    ticket.full_clean()
    ticket.save()
    MaintenanceStatusHistory.objects.create(ticket=ticket, from_status=old_status, to_status=new_status, notes=notes, actor=actor)
    if new_status in {MaintenanceTicket.Status.RESOLVED, MaintenanceTicket.Status.CANCELLED}:
        restore_ticket_unit(ticket)
    _notify_ticket_people(ticket, "maintenance_updated", "Maintenance request updated", f"{ticket.reference} is now {ticket.get_status_display().lower()}.")
    return ticket


def restore_ticket_unit(ticket):
    if not ticket.blocks_unit or not ticket.unit_id:
        return
    unit = Unit.objects.select_for_update().get(pk=ticket.unit_id)
    still_blocked = MaintenanceTicket.objects.filter(unit=unit, blocks_unit=True).exclude(pk=ticket.pk).exclude(status__in=(MaintenanceTicket.Status.RESOLVED, MaintenanceTicket.Status.CANCELLED)).exists()
    if still_blocked:
        return
    occupied = Lease.objects.filter(unit=unit, status=Lease.Status.ACTIVE).exists()
    unit.status = Unit.Status.OCCUPIED if occupied else Unit.Status.AVAILABLE
    unit.save(update_fields=("status", "updated_at"))


@dataclass(frozen=True)
class ReminderEvent:
    invoice: Invoice
    kind: str
    overdue_days: int = -1


def pending_reminder_event(invoice, config, today=None):
    today = today or timezone.localdate()
    delta = (invoice.due_date - today).days
    if delta == config.days_before:
        return ReminderEvent(invoice, "upcoming")
    if delta == 0:
        return ReminderEvent(invoice, "due_today")
    if delta > 0:
        return None
    overdue = -delta
    intervals = sorted(config.overdue_intervals or [])
    if overdue in intervals:
        return ReminderEvent(invoice, "overdue", overdue)
    if intervals and overdue > intervals[-1]:
        return ReminderEvent(invoice, "overdue", intervals[-1])
    return None


def _event_message(event, config):
    template = {"upcoming": config.upcoming_template, "due_today": config.due_template, "overdue": config.overdue_template}[event.kind]
    return template.format(invoice=event.invoice.number, due_date=event.invoice.due_date, currency=event.invoice.currency, balance=f"{event.invoice.balance:.3f}", overdue_days=event.overdue_days)


def _deliver(log, event, config):
    tenant = event.invoice.lease.primary_tenant or event.invoice.lease.tenant
    message = _event_message(event, config)
    log.attempts += 1
    try:
        if log.channel == "database":
            if not tenant.user_id:
                raise RuntimeError("Tenant has no portal user.")
            _notify_user(tenant.user, kind=f"rent_{event.kind}", title="Rent reminder", message=message, url=reverse("invoice_workspace", kwargs={"invoice_id": event.invoice.pk}), payload={"invoice": event.invoice.number})
        elif log.channel == "email":
            if not tenant.email:
                raise RuntimeError("Tenant has no email address.")
            send_mail("Rent reminder", message, getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@omanskylight.com"), [tenant.email], fail_silently=False)
        elif log.channel == "whatsapp":
            if not tenant.phone:
                raise RuntimeError("Tenant has no phone number.")
            send_whatsapp(tenant.phone, message)
        elif log.channel == "log":
            logger.info("Rent reminder for %s: %s", tenant, message)
        else:
            raise RuntimeError("Unsupported reminder channel.")
        log.status = "sent"
        log.sent_at = timezone.now()
        log.error_message = ""
    except Exception as error:
        log.status = "failed"
        log.error_message = str(error)
    log.save(update_fields=("attempts", "status", "sent_at", "error_message"))
    return log


def dispatch_reminder_event(event, config, *, manual=False):
    event.invoice.refresh_from_db()
    tenant = event.invoice.lease.primary_tenant or event.invoice.lease.tenant
    recipient = tenant.email or tenant.phone or str(tenant)
    results = []
    for channel in config.channels:
        bucket = event.overdue_days if event.kind == "overdue" else -1
        suffix = f":manual:{timezone.localdate()}" if manual else ""
        dedupe = f"invoice:{event.invoice.pk}:{event.kind}:{bucket}:{channel}{suffix}"
        log, created = ReminderLog.objects.get_or_create(dedupe_key=dedupe, defaults={"kind": event.kind, "recipient": recipient, "channel": channel, "subject_type": "billing.Invoice", "subject_id": str(event.invoice.pk), "reminder_date": timezone.localdate(), "overdue_days": bucket, "payload": {"invoice": event.invoice.number, "balance": str(event.invoice.balance), "manual": manual}})
        if not created:
            continue
        results.append(_deliver(log, event, config))
    return results


def send_due_rent_reminders(today=None):
    config = ReminderSettings.load()
    if not config.enabled:
        return 0
    today = today or timezone.localdate()
    invoices = Invoice.objects.exclude(status__in=(Invoice.Status.PAID, Invoice.Status.VOID, Invoice.Status.CANCELLED)).select_related("lease__tenant__user", "lease__primary_tenant__user")
    count = 0
    for invoice in invoices:
        event = pending_reminder_event(invoice, config, today)
        if event:
            count += len(dispatch_reminder_event(event, config))
    return count


def send_manual_invoice_reminder(invoice):
    config = ReminderSettings.load()
    today = timezone.localdate()
    event = pending_reminder_event(invoice, config, today)
    if event is None:
        kind = "overdue" if invoice.due_date < today else ("due_today" if invoice.due_date == today else "upcoming")
        event = ReminderEvent(invoice, kind, max((today - invoice.due_date).days, -1) if kind == "overdue" else -1)
    return dispatch_reminder_event(event, config, manual=True)


def send_expiration_notices(today=None):
    config = ReminderSettings.load()
    if not config.enabled:
        return 0
    today = today or timezone.localdate()
    target = today + timezone.timedelta(days=config.lease_expiration_days)
    count = 0
    leases = Lease.objects.filter(status=Lease.Status.ACTIVE, end_date=target).select_related("tenant__user", "primary_tenant__user")
    for lease in leases:
        tenant = lease.primary_tenant or lease.tenant
        key = f"lease:{lease.pk}:expiration:{target}"
        _, created = ReminderLog.objects.get_or_create(dedupe_key=key, defaults={"kind": "lease_expiration", "recipient": tenant.email or tenant.phone or str(tenant), "channel": "database", "subject_type": "properties.Lease", "subject_id": str(lease.pk), "reminder_date": today, "status": "sent", "sent_at": timezone.now(), "payload": {"end_date": str(lease.end_date)}})
        if not created:
            continue
        if tenant.user_id:
            _notify_user(tenant.user, kind="lease_expiring", title="Lease expiration reminder", message=f"Lease {lease.reference} expires on {lease.end_date}.", url=reverse("lease_workspace", kwargs={"lease_id": lease.pk}), payload={"lease": lease.reference})
        count += 1
    return count
