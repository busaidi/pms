from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO
from tempfile import TemporaryDirectory
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image
from accounts.models import Capability, GroupProfile, PropertyAccess
from .models import Property, PropertyMedia, PropertyRate, PropertyType, Unit, UnitRate, UnitType, UnitTypeRate
from .services import effective_unit_rates, publication_readiness
from .transfers import csv_response_rows, export_rows, validate_rows
from .lease_tests import LeaseLifecycleTests  # noqa: F401


class InventoryTestCase(TestCase):
    def setUp(self):
        self.kind = PropertyType.objects.create(name="Apartment", slug="apartment")
        self.property = Property.objects.create(name="Harbour House", slug="harbour-house", property_type=self.kind, address="Muscat", city="Muscat", description="Waterfront homes", public_slug="harbour-house")
        self.unit_type = UnitType.objects.create(property=self.property, name="One bedroom", public_slug="one-bedroom")
        self.unit = Unit.objects.create(property=self.property, unit_type=self.unit_type, name="101", monthly_rent=Decimal("350"))

    def test_unit_rate_overrides_matching_unit_type_rate(self):
        UnitTypeRate.objects.create(unit_type=self.unit_type, amount="300", currency="OMR", billing_unit="month", billing_interval=1)
        UnitTypeRate.objects.create(unit_type=self.unit_type, amount="80", currency="OMR", billing_unit="week", billing_interval=1)
        UnitRate.objects.create(unit=self.unit, amount="325", currency="OMR", billing_unit="month", billing_interval=1)
        rates = effective_unit_rates(self.unit)
        self.assertEqual([(item["source"], item["rate"].amount) for item in rates], [("unit type", Decimal("80")), ("unit", Decimal("325"))])

    def test_inactive_and_future_rates_are_not_effective(self):
        UnitRate.objects.create(unit=self.unit, amount="325", is_active=False)
        UnitRate.objects.create(unit=self.unit, amount="350", currency="USD", starts_on=date.today() + timedelta(days=1))
        self.assertEqual(effective_unit_rates(self.unit), [])

    def test_publication_readiness_follows_rental_mode(self):
        self.property.rental_mode = Property.RentalMode.WHOLE; self.property.save()
        self.assertFalse(publication_readiness(self.property)["ready"])
        PropertyRate.objects.create(property=self.property, amount="2500")
        self.assertTrue(publication_readiness(self.property)["ready"])
        self.property.rental_mode = Property.RentalMode.UNIT; self.property.save()
        self.assertFalse(publication_readiness(self.property)["ready"])
        UnitTypeRate.objects.create(unit_type=self.unit_type, amount="350")
        self.assertTrue(publication_readiness(self.property)["ready"])

    def test_property_with_active_lease_cannot_be_archived(self):
        from .models import Lease, Tenant
        tenant = Tenant.objects.create(full_name="Demo Tenant", phone="1")
        Lease.objects.create(unit=self.unit, tenant=tenant, start_date=date.today(), monthly_rent="350", status="active")
        with self.assertRaises(ValidationError): self.property.archive()

    def test_image_kind_rejects_document_extension(self):
        media = PropertyMedia(property=self.property, kind="image", file=SimpleUploadedFile("brochure.pdf", b"pdf"))
        with self.assertRaises(ValidationError): media.full_clean()

    def test_valid_private_image_is_stored_and_authorized(self):
        image = BytesIO(); Image.new("RGB", (2, 2), "teal").save(image, format="PNG")
        with TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            media = PropertyMedia(property=self.property, kind="image", file=SimpleUploadedFile("home.png", image.getvalue(), content_type="image/png"))
            media.full_clean(); media.save()
            self.assertEqual(self.client.get(f"/properties/media/{media.pk}/").status_code, 404)
            admin = get_user_model().objects.create_superuser("media-admin", "media@example.test", "secret-pass")
            self.client.force_login(admin)
            response = self.client.get(f"/properties/media/{media.pk}/")
            self.assertEqual(response.status_code, 200); response.close()

    def test_property_scoped_user_cannot_open_other_property(self):
        user = get_user_model().objects.create_user("manager", password="secret-pass")
        group = Group.objects.create(name="scoped-manager"); GroupProfile.objects.create(group=group, label="Scoped manager")
        capability = Capability.objects.create(name="properties.view", label="View", description="View"); capability.groups.add(group)
        PropertyAccess.objects.create(user=user, property=self.property, group=group)
        other = Property.objects.create(name="Other", slug="other", address="Other")
        self.client.force_login(user)
        self.assertEqual(self.client.get(f"/properties/{self.property.slug}/").status_code, 200)
        self.assertEqual(self.client.get(f"/properties/{other.slug}/").status_code, 404)

    def test_units_csv_validates_persists_and_exports(self):
        rows = [{"property_slug": self.property.slug, "name": "102", "slug": "102", "unit_type": self.unit_type.name, "floor": "1", "description": "Garden", "size_sqm": "72.5", "capacity": "2", "furnishing": "furnished", "status": "available", "monthly_rent": "375.000"}]
        prepared, errors = validate_rows("units", rows, None, persist=True)
        self.assertFalse(errors); self.assertEqual(len(prepared), 1)
        csv_text = csv_response_rows("units", export_rows("units", Property.objects.filter(pk=self.property.pk)))
        self.assertIn("102", csv_text); self.assertIn("375.000", csv_text)

    def test_csv_validation_is_all_or_nothing(self):
        rows = [{"slug": "villa", "label": "Villa", "default_rental_mode": "whole_property", "is_active": "1", "sort_order": "1"}, {"slug": "villa", "label": "Duplicate", "default_rental_mode": "unit", "is_active": "1", "sort_order": "2"}]
        _, errors = validate_rows("property-types", rows, None, persist=True)
        self.assertTrue(errors); self.assertFalse(PropertyType.objects.filter(slug="villa").exists())
