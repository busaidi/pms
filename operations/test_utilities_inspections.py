from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from billing.models import Invoice, InvoiceLineItem
from properties.models import Lease, Property, Tenant, Unit

from .inspections import complete_inspection, create_inspection, update_inspection
from .models import Inspection, InspectionTemplate, InspectionTemplateItem, UtilityMeter, UtilityReading
from .utilities import bill_utility_readings, correct_utility_reading, record_utility_reading, update_utility_reading


class AdvancedOperationsFixture(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser("operations-owner", "owner@example.com", "admin")
        self.property = Property.objects.create(name="Advanced House", slug="advanced-house", address="Muscat")
        self.unit = Unit.objects.create(property=self.property, name="1", monthly_rent=Decimal("100.000"), status=Unit.Status.OCCUPIED)
        self.tenant = Tenant.objects.create(full_name="Tenant", phone="1")
        self.lease = Lease.objects.create(property=self.property, unit=self.unit, tenant=self.tenant, start_date=date.today() - timedelta(days=30), monthly_rent=Decimal("100.000"), rent_amount=Decimal("100.000"), status=Lease.Status.ACTIVE)


class UtilityWorkflowTests(AdvancedOperationsFixture):
    def setUp(self):
        super().setUp(); self.meter = UtilityMeter.objects.create(unit=self.unit, kind=UtilityMeter.Kind.ELECTRICITY, serial_number="ELEC-1", rate=Decimal("0.025"), currency="OMR")

    def test_reading_continuity_calculates_consumption_and_snapshots_rate(self):
        first = record_utility_reading(meter=self.meter, reading_date=date.today() - timedelta(days=2), current_reading=100, actor=self.user)
        second = record_utility_reading(meter=self.meter, reading_date=date.today(), current_reading=125, actor=self.user)
        self.assertEqual((second.previous_reading_record, second.previous_value, second.consumption, second.rate), (first, Decimal("100"), Decimal("25"), Decimal("0.025")))

    def test_reading_cannot_go_backwards(self):
        record_utility_reading(meter=self.meter, reading_date=date.today(), current_reading=100, actor=self.user)
        with self.assertRaises(ValidationError): record_utility_reading(meter=self.meter, reading_date=date.today() + timedelta(days=1), current_reading=99, actor=self.user)

    def test_dependent_and_billed_readings_are_immutable(self):
        first = record_utility_reading(meter=self.meter, reading_date=date.today() - timedelta(days=2), current_reading=100, actor=self.user)
        record_utility_reading(meter=self.meter, reading_date=date.today(), current_reading=125, actor=self.user)
        with self.assertRaises(ValidationError): update_utility_reading(first, current_reading=101)

    def test_correction_keeps_lineage(self):
        reading = record_utility_reading(meter=self.meter, reading_date=date.today(), current_reading=100, actor=self.user)
        correction = correct_utility_reading(reading, adjustment_consumption=Decimal("-5"), actor=self.user, notes="Meter estimate")
        self.assertEqual((correction.reading_kind, correction.corrects_reading, correction.consumption), (UtilityReading.Kind.ADJUSTMENT, reading, Decimal("-5")))

    def test_billing_adds_one_invoice_line_and_prevents_duplicates(self):
        invoice = Invoice.objects.create(number="INV-UTIL", lease=self.lease, issue_date=date.today(), due_date=date.today() + timedelta(days=3), subtotal=100, total=100, currency="OMR")
        InvoiceLineItem.objects.create(invoice=invoice, type=InvoiceLineItem.Type.RENT, description="Rent", quantity=1, unit_price=100, total=100)
        reading = record_utility_reading(meter=self.meter, reading_date=date.today(), current_reading=100, actor=self.user)
        self.assertEqual(len(bill_utility_readings([reading])), 1)
        self.assertEqual(len(bill_utility_readings([reading])), 0)
        invoice.refresh_from_db(); self.assertEqual(invoice.total, Decimal("102.500")); self.assertEqual(invoice.line_items.filter(type=InvoiceLineItem.Type.UTILITY).count(), 1)


class InspectionWorkflowTests(AdvancedOperationsFixture):
    def setUp(self):
        super().setUp(); self.template = InspectionTemplate.objects.create(name="Move in", inspection_type=InspectionTemplate.Type.MOVE_IN); InspectionTemplateItem.objects.create(template=self.template, label="Walls", guidance="Check paint", sort_order=1); InspectionTemplateItem.objects.create(template=self.template, label="Windows", sort_order=2)

    def test_creation_snapshots_template_and_items(self):
        inspection = create_inspection(template=self.template, property_obj=self.property, unit=self.unit, lease=self.lease, inspection_date=date.today(), inspector=self.user)
        self.template.name = "Changed"; self.template.save()
        self.assertEqual(inspection.template_name, "Move in"); self.assertEqual(list(inspection.items.values_list("label", flat=True)), ["Walls", "Windows"])

    def test_move_inspection_requires_lease(self):
        with self.assertRaises(ValidationError): create_inspection(template=self.template, property_obj=self.property, unit=self.unit, inspection_date=date.today(), inspector=self.user)

    def test_complete_requires_all_conditions_and_locks_updates(self):
        inspection = create_inspection(template=self.template, property_obj=self.property, unit=self.unit, lease=self.lease, inspection_date=date.today(), inspector=self.user)
        with self.assertRaises(ValidationError): complete_inspection(inspection, actor=self.user)
        rows = [{"id": item.pk, "condition": "good", "notes": ""} for item in inspection.items.all()]
        update_inspection(inspection, actor=self.user, items=rows); complete_inspection(inspection, actor=self.user); inspection.refresh_from_db(); self.assertEqual(inspection.status, Inspection.Status.COMPLETED)
        with self.assertRaises(ValidationError): update_inspection(inspection, actor=self.user, notes="Changed")

    def test_global_workspaces_render(self):
        inspection = create_inspection(template=self.template, property_obj=self.property, unit=self.unit, lease=self.lease, inspection_date=date.today(), inspector=self.user)
        self.client.force_login(self.user)
        self.assertContains(self.client.get(reverse("utility_list")), "Utility meters")
        self.assertContains(self.client.get(reverse("inspection_workspace", args=[inspection.pk])), "Inspection workspace")
