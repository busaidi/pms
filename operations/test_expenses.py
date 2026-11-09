from datetime import date, timedelta
from decimal import Decimal
import tempfile

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from billing.models import Invoice, InvoiceLineItem, Payment, PaymentAllocation
from properties.models import Lease, Property, Tenant, Unit

from .expenses import create_recurring_expense, generate_recurring_expenses, next_occurrence, record_expense, set_schedule_paused, void_expense
from .models import Expense, ExpenseCategory, RecurringExpense
from .reports import financial_report


class ExpenseFixture(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser("finance", "finance@example.com", "admin")
        self.property = Property.objects.create(name="Finance House", slug="finance-house", address="Muscat")
        self.category = ExpenseCategory.objects.create(name="Maintenance", slug="maintenance")


class ExpenseWorkflowTests(ExpenseFixture):
    def test_record_and_void_preserves_audit_state(self):
        expense = record_expense(actor=self.user, property=self.property, category=self.category, amount=Decimal("12.345"), currency="omr", incurred_on=date.today(), description="Repair")
        self.assertEqual(expense.currency, "OMR")
        void_expense(expense, actor=self.user, reason="Duplicate")
        expense.refresh_from_db()
        self.assertEqual((expense.status, expense.void_reason, expense.voided_by), (Expense.Status.VOIDED, "Duplicate", self.user))

    def test_void_requires_reason(self):
        expense = record_expense(actor=self.user, property=self.property, category=self.category, amount=1, currency="OMR", incurred_on=date.today(), description="Repair")
        with self.assertRaises(ValidationError):
            void_expense(expense, actor=self.user, reason="")

    @override_settings(MEDIA_ROOT=tempfile.mkdtemp())
    def test_private_receipt_download_requires_expense_access(self):
        receipt = SimpleUploadedFile("receipt.pdf", b"%PDF-test", content_type="application/pdf")
        expense = record_expense(actor=self.user, property=self.property, category=self.category, amount=1, currency="OMR", incurred_on=date.today(), description="Repair", receipt=receipt)
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("expense_receipt", args=[expense.pk])).status_code, 200)

    def test_csv_export_contains_expense(self):
        record_expense(actor=self.user, property=self.property, category=self.category, amount=1, currency="OMR", incurred_on=date.today(), description="Repair")
        self.client.force_login(self.user)
        response = self.client.get(reverse("expense_export"))
        self.assertContains(response, "Finance House")
        self.assertEqual(response["Content-Type"], "text/csv")


class RecurringExpenseTests(ExpenseFixture):
    def test_month_end_schedule_does_not_drift(self):
        schedule = RecurringExpense(property=self.property, category=self.category, amount=10, description="Monthly", billing_interval=1, billing_unit="month", start_date=date(2026, 1, 31), next_run_on=date(2026, 1, 31))
        self.assertEqual(next_occurrence(schedule, date(2026, 1, 31)), date(2026, 2, 28))

    def test_generation_is_idempotent_and_advances_schedule(self):
        schedule = create_recurring_expense(actor=self.user, property=self.property, category=self.category, amount=10, currency="OMR", description="Daily security", vendor="Guard", billing_interval=1, billing_unit="day", start_date=date.today() - timedelta(days=1), ends_on=None, notes="")
        self.assertEqual(generate_recurring_expenses(today=date.today(), actor=self.user), 2)
        self.assertEqual(generate_recurring_expenses(today=date.today(), actor=self.user), 0)
        self.assertEqual(Expense.objects.filter(recurring_expense=schedule).count(), 2)

    def test_pause_and_resume_skips_past_occurrences(self):
        schedule = create_recurring_expense(actor=self.user, property=self.property, category=self.category, amount=10, currency="OMR", description="Weekly", vendor="", billing_interval=1, billing_unit="week", start_date=date.today() - timedelta(days=20), ends_on=None, notes="")
        set_schedule_paused(schedule, True); schedule.refresh_from_db(); self.assertTrue(schedule.is_paused)
        set_schedule_paused(schedule, False); schedule.refresh_from_db(); self.assertGreater(schedule.next_run_on, date.today())


class FinancialReportTests(ExpenseFixture):
    def test_report_reconciles_revenue_expense_collection_and_noi(self):
        unit = Unit.objects.create(property=self.property, name="1", monthly_rent=100)
        tenant = Tenant.objects.create(full_name="Tenant", phone="1")
        lease = Lease.objects.create(property=self.property, unit=unit, tenant=tenant, start_date=date.today(), monthly_rent=100, status=Lease.Status.ACTIVE)
        invoice = Invoice.objects.create(number="INV-RPT", lease=lease, issue_date=date.today(), due_date=date.today(), total=Decimal("100.000"), subtotal=Decimal("100.000"))
        payment = Payment.objects.create(reference="PAY-RPT", invoice=invoice, tenant=tenant, amount=Decimal("40.000"), currency="OMR", status=Payment.Status.CONFIRMED)
        PaymentAllocation.objects.create(payment=payment, invoice=invoice, amount=Decimal("40.000"))
        record_expense(actor=self.user, property=self.property, category=self.category, amount=Decimal("30.000"), currency="OMR", incurred_on=date.today(), description="Repair")
        report = financial_report(Property.objects.all())
        self.assertEqual(report["revenue"][0]["amount"], Decimal("100.000"))
        self.assertEqual(report["expenses"][0]["amount"], Decimal("30.000"))
        self.assertEqual(report["noi"][0]["amount"], Decimal("70.000"))
        self.assertEqual(report["collected"][0]["amount"], Decimal("40.000"))

    def test_financial_and_rent_dashboards_render(self):
        self.client.force_login(self.user)
        self.assertContains(self.client.get(reverse("financial_dashboard")), "Financial dashboard")
        self.assertContains(self.client.get(reverse("rent_dashboard")), "Rent collection")
