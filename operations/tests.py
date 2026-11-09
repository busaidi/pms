from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from billing.models import Invoice
from properties.models import Lease, Property, Tenant, Unit

from .models import MaintenanceStatusHistory, MaintenanceTicket, ReminderLog, ReminderSettings, UserNotification
from .services import ReminderEvent, create_ticket, dispatch_reminder_event, pending_reminder_event, send_due_rent_reminders, send_expiration_notices, transition_ticket


class OperationsFixture(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("ops-admin", "ops@example.com", "admin")
        self.tenant_user = get_user_model().objects.create_user("tenant", "tenant@example.com", "test-pass")
        self.property = Property.objects.create(name="Operations House", slug="operations-house", address="Muscat")
        self.unit = Unit.objects.create(property=self.property, name="12", monthly_rent="725.000", status=Unit.Status.AVAILABLE)
        self.tenant = Tenant.objects.create(user=self.tenant_user, full_name="Demo Tenant", email="tenant@example.com", phone="90000000", portal_enabled=True)

    def make_lease(self, **overrides):
        values = {"property": self.property, "unit": self.unit, "tenant": self.tenant, "primary_tenant": self.tenant, "start_date": timezone.localdate() - timedelta(days=30), "end_date": timezone.localdate() + timedelta(days=30), "monthly_rent": "725.000", "rent_amount": "725.000", "status": Lease.Status.ACTIVE}
        values.update(overrides)
        return Lease.objects.create(**values)

    def make_invoice(self, due_date=None, **overrides):
        lease = overrides.pop("lease", None) or self.make_lease()
        values = {"number": f"INV-{Invoice.objects.count() + 1}", "lease": lease, "issue_date": timezone.localdate() - timedelta(days=5), "due_date": due_date or timezone.localdate(), "subtotal": "725.000", "total": "725.000", "status": Invoice.Status.PENDING}
        values.update(overrides)
        return Invoice.objects.create(**values)


class MaintenanceWorkflowTests(OperationsFixture):
    def test_create_blocks_unit_and_records_history_and_notification(self):
        ticket = create_ticket(actor=self.admin, property=self.property, unit=self.unit, tenant=self.tenant, title="Leaking faucet", description="Water under sink", priority="urgent", block_unit=True)
        self.assertTrue(ticket.reference.startswith(f"TKT{timezone.localdate().year}"))
        self.assertEqual(Unit.objects.get(pk=self.unit.pk).status, Unit.Status.MAINTENANCE)
        self.assertEqual(MaintenanceStatusHistory.objects.get(ticket=ticket).to_status, MaintenanceTicket.Status.REPORTED)
        self.assertTrue(UserNotification.objects.filter(recipient=self.tenant_user, kind="maintenance_created").exists())

    def test_transition_rules_require_in_progress_and_resolution_notes(self):
        ticket = create_ticket(actor=self.admin, property=self.property, unit=self.unit, title="Broken lock", description="Door will not lock", priority="high")
        with self.assertRaisesMessage(ValidationError, "cannot move"):
            transition_ticket(ticket, MaintenanceTicket.Status.RESOLVED, actor=self.admin, notes="Fixed")
        ticket = transition_ticket(ticket, MaintenanceTicket.Status.IN_PROGRESS, actor=self.admin)
        with self.assertRaisesMessage(ValidationError, "required"):
            transition_ticket(ticket, MaintenanceTicket.Status.RESOLVED, actor=self.admin)
        ticket = transition_ticket(ticket, MaintenanceTicket.Status.RESOLVED, actor=self.admin, notes="Replaced lock")
        self.assertIsNotNone(ticket.resolved_at)
        self.assertEqual(ticket.history.count(), 3)

    def test_resolving_restores_occupied_unit_from_active_lease(self):
        self.make_lease()
        ticket = create_ticket(actor=self.admin, property=self.property, unit=self.unit, title="Air conditioner", description="Not cooling", priority="high", block_unit=True)
        transition_ticket(ticket, MaintenanceTicket.Status.IN_PROGRESS, actor=self.admin)
        transition_ticket(ticket, MaintenanceTicket.Status.RESOLVED, actor=self.admin, notes="Compressor replaced")
        self.unit.refresh_from_db()
        self.assertEqual(self.unit.status, Unit.Status.OCCUPIED)

    def test_other_active_ticket_keeps_unit_blocked(self):
        first = create_ticket(actor=self.admin, property=self.property, unit=self.unit, title="AC", description="Fault", priority="high", block_unit=True)
        create_ticket(actor=self.admin, property=self.property, unit=self.unit, title="Pipe", description="Leak", priority="urgent", block_unit=True)
        transition_ticket(first, MaintenanceTicket.Status.IN_PROGRESS, actor=self.admin)
        transition_ticket(first, MaintenanceTicket.Status.RESOLVED, actor=self.admin, notes="Fixed")
        self.unit.refresh_from_db()
        self.assertEqual(self.unit.status, Unit.Status.MAINTENANCE)

    def test_workspace_and_private_notification_ownership(self):
        ticket = create_ticket(actor=self.admin, property=self.property, unit=self.unit, title="Light", description="Failed", priority="medium")
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse("maintenance_workspace", args=[ticket.pk])), ticket.reference)
        notification = UserNotification.objects.create(recipient=self.tenant_user, kind="private", title="Private", message="Only tenant")
        self.assertEqual(self.client.post(reverse("notification_read", args=[notification.pk])).status_code, 404)


class ReminderWorkflowTests(OperationsFixture):
    def setUp(self):
        super().setUp()
        self.config = ReminderSettings.load()
        self.config.channels = ["database", "log"]
        self.config.overdue_intervals = [1, 3, 7]
        self.config.save()

    def test_scheduler_selects_upcoming_due_and_overdue_buckets(self):
        today = timezone.localdate()
        upcoming = pending_reminder_event(self.make_invoice(today + timedelta(days=3)), self.config, today)
        due = pending_reminder_event(self.make_invoice(today), self.config, today)
        overdue = pending_reminder_event(self.make_invoice(today - timedelta(days=15)), self.config, today)
        self.assertEqual(upcoming.kind, "upcoming")
        self.assertEqual(due.kind, "due_today")
        self.assertEqual((overdue.kind, overdue.overdue_days), ("overdue", 7))

    def test_scheduled_delivery_is_deduplicated_per_channel(self):
        invoice = self.make_invoice()
        self.assertEqual(send_due_rent_reminders(), 2)
        self.assertEqual(send_due_rent_reminders(), 0)
        self.assertEqual(ReminderLog.objects.filter(subject_id=str(invoice.pk)).count(), 2)
        self.assertEqual(UserNotification.objects.filter(recipient=self.tenant_user, kind="rent_due_today").count(), 1)

    def test_driver_failure_is_recorded_without_stopping_other_channels(self):
        self.config.channels = ["whatsapp", "log"]
        self.config.save()
        logs = dispatch_reminder_event(ReminderEvent(self.make_invoice(), "due_today"), self.config)
        self.assertEqual([log.status for log in logs], ["failed", "sent"])
        self.assertIn("disabled", logs[0].error_message)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_email_driver_sends_and_records_success(self):
        self.config.channels = ["email"]
        self.config.save()
        logs = dispatch_reminder_event(ReminderEvent(self.make_invoice(), "due_today"), self.config)
        self.assertEqual(logs[0].status, "sent")
        from django.core import mail
        self.assertEqual(len(mail.outbox), 1)

    def test_lease_expiration_notification_is_deduplicated(self):
        self.make_lease()
        self.assertEqual(send_expiration_notices(), 1)
        self.assertEqual(send_expiration_notices(), 0)
        self.assertEqual(UserNotification.objects.filter(kind="lease_expiring").count(), 1)

    def test_reminder_settings_and_manual_run_require_permissions(self):
        self.client.force_login(self.tenant_user)
        self.assertEqual(self.client.get(reverse("reminder_settings")).status_code, 403)
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse("reminder_settings")), "Rent reminders")
        self.assertEqual(self.client.post(reverse("run_reminders")).status_code, 302)
