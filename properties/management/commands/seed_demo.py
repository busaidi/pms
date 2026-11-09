from datetime import date, datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import AppSetting, UserProfile
from billing.models import Invoice, InvoiceLineItem, Payment, PaymentAllocation
from billing.services import generate_invoices, recalculate_invoice
from integrations.models import Integration
from integrations.services import synchronize_extensions
from operations.models import (
    Expense,
    ExpenseCategory,
    Inspection,
    InspectionItem,
    InspectionTemplate,
    InspectionTemplateItem,
    MaintenanceTicket,
    MaintenanceStatusHistory,
    ReminderSettings,
    UtilityMeter,
    UtilityReading,
)
from portal.models import Application
from properties.models import Amenity, City, Lease, Property, PropertyRate, PropertyType, Region, Tenant, Unit, UnitRate, UnitType, UnitTypeRate
from properties.lease_services import generate_rent_schedule
from properties.services import effective_unit_rates
from django.utils.translation import gettext_lazy as _


class Command(BaseCommand):
    help = "Create an idempotent Oman Skylight demonstration portfolio"

    def handle(self, *args, **options):
        manager = get_user_model().objects.filter(is_superuser=True).order_by("id").first()
        if manager is None:
            self.stderr.write("Create a superuser before loading demo operational data.")
            return
        UserProfile.objects.get_or_create(user=manager, defaults={"phone": "92110000", "email_verified_at": timezone.now()})
        for group_name in ("Owner", "Property Manager", "Accountant", "Maintenance", "Tenant"):
            Group.objects.get_or_create(name=group_name)
        apartment_type, _created = PropertyType.objects.get_or_create(name="Apartment building", defaults={"slug": "apartment-building", "default_rental_mode": "unit", "sort_order": 10})
        villa_type, _created = PropertyType.objects.get_or_create(name="Villa community", defaults={"slug": "villa-community", "default_rental_mode": "hybrid", "sort_order": 20})
        region, _created = Region.objects.get_or_create(name="Muscat", country_code="OM")
        city, _created = City.objects.get_or_create(name="Muscat", region=region)
        amenities = [Amenity.objects.get_or_create(name=name)[0] for name in ("Parking", "Swimming pool", "Security", "Gym")]
        portfolio = [
            (
                "Al Mouj Waves",
                "Al Mouj, Muscat",
                "al-mouj-waves",
                apartment_type,
                [("A-101", "725.000", "occupied"), ("A-102", "700.000", "available"), ("B-204", "850.000", "occupied")],
            ),
            (
                "Qurum Heights",
                "Qurum, Muscat",
                "qurum-heights",
                villa_type,
                [("Villa 8", "1200.000", "occupied"), ("Villa 12", "1350.000", "maintenance")],
            ),
            (
                "Madinat Al Ilam",
                "Madinat Al Ilam, Muscat",
                "madinat-al-ilam",
                apartment_type,
                [("A-201", "950.000", "occupied"), ("A-202", "925.000", "available")],
            ),
        ]
        units = {}
        properties = {}
        for name, address, slug, property_type, unit_rows in portfolio:
            property_obj, _created = Property.objects.update_or_create(
                name=name,
                defaults={"address": address, "slug": slug, "public_slug": slug, "property_type": property_type, "city": "Muscat", "region": "Muscat", "city_ref": city, "region_ref": region, "description": f"Managed homes at {name}, Muscat.", "rental_mode": "hybrid" if name == "Qurum Heights" else "unit", "is_public": True, "is_published": True, "is_active": True},
            )
            properties[name] = property_obj
            property_obj.amenities.set(amenities)
            unit_type, _created = UnitType.objects.update_or_create(
                property=property_obj,
                name="Villa" if property_type == villa_type else "Two bedroom",
                defaults={"public_slug": "villa" if property_type == villa_type else "two-bedroom", "bedrooms": 2, "bathrooms": Decimal("2.0"), "is_active": True, "is_published": True},
            )
            UnitTypeRate.objects.update_or_create(unit_type=unit_type, billing_interval=1, billing_unit="month", currency="OMR", starts_on=date(2026, 1, 1), defaults={"amount": Decimal(unit_rows[0][1]), "is_active": True})
            for unit_name, rent, status in unit_rows:
                units[(name, unit_name)], _created = Unit.objects.update_or_create(
                    property=property_obj,
                    name=unit_name,
                    defaults={"unit_type": unit_type, "monthly_rent": Decimal(rent), "bedrooms": 2, "bathrooms": Decimal("2.0"), "status": status},
                )

        whole_property, _created = Property.objects.update_or_create(
            name="Jabal Akhdar Retreat",
            defaults={"slug": "jabal-akhdar-retreat", "public_slug": "jabal-akhdar-retreat", "property_type": villa_type, "rental_mode": "whole_property", "address": "Al Jabal Al Akhdar", "city": "Nizwa", "region": "Ad Dakhiliyah", "description": "A private whole-property mountain retreat.", "is_active": True, "is_public": True, "is_published": True},
        )
        PropertyRate.objects.update_or_create(property=whole_property, billing_interval=1, billing_unit="day", currency="OMR", starts_on=date(2026, 1, 1), defaults={"amount": Decimal("180.000"), "is_active": True})
        PropertyRate.objects.update_or_create(property=properties["Qurum Heights"], billing_interval=1, billing_unit="month", currency="OMR", starts_on=date(2026, 1, 1), defaults={"amount": Decimal("5500.000"), "is_active": True})
        UnitRate.objects.update_or_create(unit=units[("Al Mouj Waves", "A-102")], billing_interval=1, billing_unit="month", currency="OMR", starts_on=date(2026, 7, 1), defaults={"amount": Decimal("690.000"), "is_active": True})

        tenants = [
            ("Ahmed Al Balushi", "92110001", "ahmed@example.test", "OM-1001"),
            ("Sara Al Hinai", "92110002", "sara@example.test", "OM-1002"),
            ("Salim Al Harthy", "92110003", "salim@example.test", "OM-1003"),
            ("Mariam Al Rawahi", "92110004", "mariam@example.test", "OM-1004"),
            ("Layla Al Kindi", "92110006", "layla@example.test", "OM-1006"),
        ]
        tenant_objects = {}
        for full_name, phone, email, id_number in tenants:
            tenant_objects[full_name], _created = Tenant.objects.update_or_create(
                id_number=id_number,
                defaults={"full_name": full_name, "phone": phone, "email": email, "is_active": True},
            )
        demo_resident = tenant_objects["Ahmed Al Balushi"]
        demo_resident.user = manager
        demo_resident.portal_enabled = True
        demo_resident.save(update_fields=("user", "portal_enabled", "updated_at"))

        lease_rows = [
            ("Ahmed Al Balushi", "Al Mouj Waves", "A-101", "725.000"),
            ("Sara Al Hinai", "Al Mouj Waves", "B-204", "850.000"),
            ("Salim Al Harthy", "Qurum Heights", "Villa 8", "1200.000"),
            ("Mariam Al Rawahi", "Madinat Al Ilam", "A-201", "950.000"),
        ]
        leases = {}
        for tenant_name, property_name, unit_name, rent in lease_rows:
            unit = units[(property_name, unit_name)]
            effective = effective_unit_rates(unit)[0]["rate"]
            lease, _created = Lease.objects.update_or_create(
                unit=unit,
                tenant=tenant_objects[tenant_name],
                status=Lease.Status.ACTIVE,
                defaults={
                    "property": unit.property,
                    "primary_tenant": tenant_objects[tenant_name],
                    "start_date": date(2026, 1, 1),
                    "end_date": date(2026, 12, 31),
                    "monthly_rent": Decimal(rent),
                    "rent_amount": Decimal(rent),
                    "currency": effective.currency,
                    "unit_rate": effective if isinstance(effective, UnitRate) else None,
                    "unit_type_rate": effective if isinstance(effective, UnitTypeRate) else None,
                    "security_deposit": Decimal(rent),
                },
            )
            lease.tenants.add(tenant_objects[tenant_name])
            generate_rent_schedule(lease)
            leases[tenant_name] = lease

        whole_rate = PropertyRate.objects.get(property=whole_property, billing_interval=1, billing_unit="day", currency="OMR")
        whole_lease, _created = Lease.objects.update_or_create(
            property=whole_property, unit=None, tenant=tenant_objects["Layla Al Kindi"], status=Lease.Status.ACTIVE,
            defaults={"primary_tenant": tenant_objects["Layla Al Kindi"], "start_date": date(2026, 10, 1), "end_date": date(2026, 10, 7), "monthly_rent": whole_rate.amount, "rent_amount": whole_rate.amount, "currency": whole_rate.currency, "billing_interval": whole_rate.billing_interval, "billing_unit": whole_rate.billing_unit, "property_rate": whole_rate, "security_deposit": Decimal("180.000")},
        )
        whole_lease.tenants.add(tenant_objects["Layla Al Kindi"])
        generate_rent_schedule(whole_lease)

        invoice, _created = Invoice.objects.update_or_create(
            number="INV-2026-0001",
            defaults={"lease": leases["Ahmed Al Balushi"], "period_start": date(2026, 9, 1), "period_end": date(2026, 9, 30), "issue_date": date(2026, 9, 1), "due_date": date(2026, 9, 7), "currency": "OMR", "subtotal": Decimal("725.000"), "total": Decimal("725.000"), "status": Invoice.Status.PAID},
        )
        InvoiceLineItem.objects.update_or_create(
            invoice=invoice,
            description="September 2026 rent",
            defaults={"type": InvoiceLineItem.Type.RENT, "quantity": 1, "unit_price": Decimal("725.000"), "total": Decimal("725.000")},
        )
        payment, _created = Payment.objects.update_or_create(
            reference="PAY-2026-0001",
            defaults={"invoice": invoice, "tenant": tenant_objects["Ahmed Al Balushi"], "amount": Decimal("725.000"), "currency": "OMR", "method": "bank_transfer", "status": Payment.Status.CONFIRMED, "payment_date": date(2026, 9, 5), "paid_at": timezone.now(), "recorded_by": manager, "confirmed_by": manager, "verified_by": manager, "verified_at": timezone.now()},
        )
        PaymentAllocation.objects.update_or_create(payment=payment, invoice=invoice, defaults={"amount": Decimal("725.000")})
        recalculate_invoice(invoice, today=date(2026, 9, 29))
        generate_invoices(today=date(2026, 9, 29), horizon=date(2026, 11, 30))

        maintenance_category, _created = ExpenseCategory.objects.get_or_create(name="Maintenance")
        Expense.objects.update_or_create(
            property=properties["Qurum Heights"],
            incurred_on=date(2026, 9, 15),
            description="Air-conditioning service",
            defaults={"category": maintenance_category, "amount": Decimal("85.000"), "vendor": "Muscat Cooling Services", "created_by": manager},
        )
        maintenance_ticket, _created = MaintenanceTicket.objects.update_or_create(
            property=properties["Qurum Heights"], unit=units[("Qurum Heights", "Villa 12")], title="Air conditioning not cooling",
            defaults={"description": "Living room AC requires inspection.", "priority": MaintenanceTicket.Priority.HIGH, "status": MaintenanceTicket.Status.IN_PROGRESS, "assigned_to": manager, "created_by": manager, "blocks_unit": True},
        )
        MaintenanceStatusHistory.objects.get_or_create(ticket=maintenance_ticket, to_status=MaintenanceTicket.Status.IN_PROGRESS, defaults={"notes": "Assigned to the maintenance manager.", "actor": manager})
        ReminderSettings.objects.get_or_create(pk=1, defaults={"overdue_intervals": [1, 3, 7], "channels": ["database", "log"]})
        meter, _created = UtilityMeter.objects.get_or_create(unit=units[("Al Mouj Waves", "A-101")], serial_number="ELEC-AMW-A101", defaults={"kind": UtilityMeter.Kind.ELECTRICITY, "unit_of_measure": "kWh", "rate": Decimal("0.025"), "currency": "OMR"})
        UtilityReading.objects.update_or_create(
            meter=meter,
            read_at=timezone.make_aware(datetime(2026, 9, 28, 9, 0)),
            defaults={"value": Decimal("12450.000"), "previous_value": Decimal("12190.000"), "rate": Decimal("0.02500"), "charge": Decimal("6.500"), "recorded_by": manager, "reading_date": date(2026, 9, 28), "period_start": date(2026, 9, 1), "period_end": date(2026, 9, 28), "current_reading": Decimal("12450.000"), "consumption": Decimal("260.000"), "currency": "OMR", "reference": "UTL202600001"},
        )
        template, _created = InspectionTemplate.objects.get_or_create(name="Move-in inspection", defaults={"description": "Standard handover condition report", "inspection_type": InspectionTemplate.Type.MOVE_IN})
        template_item, _created = InspectionTemplateItem.objects.get_or_create(template=template, label=_("Walls and paint"), defaults={"sort_order": 1})
        inspection, _created = Inspection.objects.update_or_create(
            template=template, unit=units[("Madinat Al Ilam", "A-201")], scheduled_for=timezone.make_aware(datetime(2026, 10, 3, 10, 0)),
            defaults={"property": properties["Madinat Al Ilam"], "lease": leases["Mariam Al Rawahi"], "template_name": template.name, "inspection_type": InspectionTemplate.Type.MOVE_IN, "inspection_date": date(2026, 10, 3), "inspector": manager, "status": Inspection.Status.DRAFT},
        )
        InspectionItem.objects.get_or_create(inspection=inspection, label=template_item.label, defaults={"sort_order": 1})
        application_unit = units[("Al Mouj Waves", "A-102")]
        application_rate = effective_unit_rates(application_unit)[0]["rate"]
        Application.objects.update_or_create(
            property=properties["Al Mouj Waves"], email="fatma@example.test",
            defaults={"user": manager, "unit": application_unit, "unit_type": application_unit.unit_type, "target_type": Application.TargetType.UNIT_TYPE, "full_name": "Fatma Al Farsi", "phone": "92110005", "desired_move_in": date(2026, 11, 1), "status": Application.Status.REVIEWING, "assigned_to": manager, "rental_billing_unit": application_rate.billing_unit, "rental_billing_interval": application_rate.billing_interval, "rental_currency": application_rate.currency, "rental_amount": application_rate.amount, "open_application_key": f"user:{manager.pk}|unit_type|{properties['Al Mouj Waves'].pk}|{application_unit.unit_type_id}"},
        )
        AppSetting.objects.update_or_create(key="general.currency", defaults={"group": "general", "value": {"code": "OMR", "decimal_places": 3}})
        Integration.objects.get_or_create(name="Manual bank transfer", defaults={"kind": Integration.Kind.PAYMENT, "provider": "manual", "is_enabled": True})
        Integration.objects.get_or_create(name="Django email", defaults={"kind": Integration.Kind.EMAIL, "provider": "console", "is_enabled": True})
        Integration.objects.get_or_create(name="WhatsApp log", defaults={"kind": Integration.Kind.WHATSAPP, "provider": "log", "is_enabled": True})
        synchronize_extensions()
        self.stdout.write(
            self.style.SUCCESS(
                f"Demo ready: {Property.objects.count()} properties, "
                f"{Unit.objects.count()} units, {Tenant.objects.count()} tenants, "
                f"{Lease.objects.count()} leases."
            )
        )
