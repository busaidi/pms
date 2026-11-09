from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.test import TestCase
from django.utils import timezone

from billing.models import Invoice
from portal.services import resolve_offer
from .lease_alerts import lease_alerts_for
from .lease_services import move_out_lease, renew_lease, terminate_lease
from . import lease_tests
from .models import Lease, Unit


class HandoverTests(TestCase):
    create_unit_lease = lease_tests.LeaseLifecycleTests.create_unit_lease

    def setUp(self):
        lease_tests.LeaseLifecycleTests.setUp(self)
        self.today = timezone.localdate()
        self.operator = get_user_model().objects.create_superuser("handover-operator", "operator@example.test", "test-password")

    def expired(self):
        return self.create_unit_lease(start_date=self.today - timedelta(days=4), end_date=self.today - timedelta(days=1))

    def test_expiry_preserves_occupancy_and_requires_confirmation(self):
        lease = self.expired()
        self.assertTrue(lease.awaiting_action)
        for operation in (terminate_lease, move_out_lease):
            with self.assertRaises(ValidationError):
                operation(lease, end_date=self.today, reason="Leaving")
        lease.refresh_from_db()
        self.unit.refresh_from_db()
        self.assertEqual(lease.status, Lease.Status.ACTIVE)
        self.assertEqual(self.unit.status, Unit.Status.OCCUPIED)
        self.assertIsNone(lease.handover_confirmed_at)

    def test_confirmed_handover_preserves_contract_dates_and_invoice_balance(self):
        lease = self.expired()
        original_end = lease.end_date
        Invoice.objects.create(number="INV-HANDOVER", lease=lease, issue_date=self.today, due_date=self.today, total="50", subtotal="50", status="overdue")
        move_out_lease(lease, end_date=self.today, reason="Leaving", handover_confirmed=True, actor=self.operator)
        lease.refresh_from_db()
        self.unit.refresh_from_db()
        self.assertEqual(lease.end_date, original_end)
        self.assertEqual(lease.move_out_date, self.today)
        self.assertEqual(lease.handover_confirmed_by, self.operator)
        self.assertIsNotNone(lease.handover_confirmed_at)
        self.assertEqual(lease.outstanding_balance, Decimal("50"))
        self.assertEqual(self.unit.status, Unit.Status.AVAILABLE)
        self.assertFalse(lease_alerts_for(self.operator).exists())

    def test_future_handover_cannot_release_unit(self):
        lease = self.expired()
        with self.assertRaises(ValidationError):
            move_out_lease(lease, end_date=self.today + timedelta(days=1), reason="Future", handover_confirmed=True)
        self.unit.refresh_from_db()
        self.assertEqual(self.unit.status, Unit.Status.OCCUPIED)

    def test_renew_expired_lease_keeps_unit_occupied(self):
        lease = self.expired()
        renewed = renew_lease(lease, end_date=self.today + timedelta(days=30), rent_amount="300")
        self.unit.refresh_from_db()
        self.assertEqual(self.unit.status, Unit.Status.OCCUPIED)
        self.assertEqual(renewed.start_date, self.today)
        self.assertFalse(renewed.awaiting_action)

    def test_one_day_lease_alert_and_midnight_boundary(self):
        lease = self.create_unit_lease(start_date=self.today, end_date=self.today)
        self.assertFalse(lease.awaiting_action)
        self.assertEqual(lease.notification_events.get().scheduled_for, self.today)
        self.assertIn(lease, lease_alerts_for(self.operator))
        self.client.force_login(self.operator)
        self.assertContains(self.client.get(reverse("lease_expirations")), "ينتهي اليوم")
        with patch("django.utils.timezone.localdate", return_value=self.today + timedelta(days=1)):
            self.assertTrue(lease.awaiting_action)
        self.unit.refresh_from_db()
        self.assertEqual(self.unit.status, Unit.Status.OCCUPIED)

    def test_alerts_are_scoped_and_include_overdue_but_not_open_ended(self):
        lease = self.expired()
        outsider = get_user_model().objects.create_user("outsider")
        self.assertFalse(lease_alerts_for(outsider).exists())
        self.assertIn(lease, lease_alerts_for(self.operator))
        lease.end_date = None
        lease.save()
        self.assertFalse(lease_alerts_for(self.operator).exists())
        self.assertFalse(lease.awaiting_action)

    def test_30_day_alert_boundary(self):
        lease = self.create_unit_lease(start_date=self.today, end_date=self.today + timedelta(days=31))
        self.assertFalse(lease_alerts_for(self.operator).exists())
        with patch("django.utils.timezone.localdate", return_value=self.today + timedelta(days=1)):
            self.assertIn(lease, lease_alerts_for(self.operator))

    def test_public_offer_blocks_occupied_units_and_whole_property(self):
        self.expired()
        self.other.status = Unit.Status.UNAVAILABLE
        self.other.save()
        # Even an accidentally changed unit status must not bypass an open lease.
        self.unit.status = Unit.Status.AVAILABLE
        self.unit.save()
        self.assertIsNone(resolve_offer(self.property, self.unit_type))
        self.assertIsNone(resolve_offer(self.property))

    def test_handover_does_not_override_maintenance(self):
        lease = self.expired()
        self.unit.status = Unit.Status.MAINTENANCE
        self.unit.save()
        move_out_lease(lease, end_date=self.today, reason="Leaving", handover_confirmed=True)
        self.unit.refresh_from_db()
        self.assertEqual(self.unit.status, Unit.Status.MAINTENANCE)

    def test_failed_settlement_rolls_back_handover_and_release(self):
        lease = self.expired()
        with self.assertRaises(ValidationError):
            move_out_lease(lease, end_date=self.today, reason="Leaving", handover_confirmed=True,
                           settlement={"refund_amount": "999", "deductions": []})
        lease.refresh_from_db()
        self.unit.refresh_from_db()
        self.assertIsNone(lease.handover_confirmed_at)
        self.assertEqual(lease.status, Lease.Status.ACTIVE)
        self.assertEqual(self.unit.status, Unit.Status.OCCUPIED)

    def test_http_actions_cannot_bypass_handover_confirmation(self):
        lease = self.expired()
        self.client.force_login(self.operator)
        for action in ("lease_terminate", "lease_move_out"):
            response = self.client.post(reverse(action, args=[lease.pk]), {"end_date": str(self.today), "reason": "Leaving"})
            self.assertEqual(response.status_code, 302)
            lease.refresh_from_db()
            self.assertEqual(lease.status, Lease.Status.ACTIVE)
        self.assertContains(self.client.get(reverse("lease_list"), {"status": "awaiting_action"}), lease.reference)
        self.assertContains(self.client.get(reverse("lease_workspace", args=[lease.pk])), 'name="handover_confirmed" required')
        self.assertContains(self.client.get(reverse("lease_expirations"), {"days": "bad"}), "بانتظار الإجراء")
        self.client.post(reverse("lease_move_out", args=[lease.pk]), {
            "end_date": str(self.today), "reason": "Received keys", "handover_confirmed": "on",
        })
        from accounts.models import AuditLog
        entry = AuditLog.objects.get(action="properties.lease.updated", target_id=str(lease.pk))
        self.assertEqual(entry.actor, self.operator)
        self.assertIsNotNone(entry.changes["after"]["handover_confirmed_at"])
        lease.refresh_from_db()
        self.assertEqual(lease.handover_confirmed_by, self.operator)
