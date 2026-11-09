from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from properties.models import Property, Unit, UnitType, UnitTypeRate

from .models import Application


class PublicListingTests(TestCase):
    def setUp(self):
        self.property = Property.objects.create(
            name="Public Home",
            slug="public-home",
            public_slug="public-home",
            address="Muscat",
            description="A public home in Muscat.",
            is_public=True,
            is_published=True,
        )
        self.unit_type = UnitType.objects.create(
            property=self.property,
            name="Two bedroom",
            public_slug="two-bedroom",
            is_published=True,
        )
        UnitTypeRate.objects.create(
            unit_type=self.unit_type,
            amount=Decimal("600.000"),
        )
        self.unit = Unit.objects.create(
            property=self.property,
            unit_type=self.unit_type,
            name="101",
            monthly_rent=Decimal("600.000"),
            status=Unit.Status.AVAILABLE,
        )

    def test_public_property_is_listed(self):
        response = self.client.get(reverse("listing_index"))
        self.assertContains(response, "Public Home")

    def test_application_submission_is_attached_to_available_unit(self):
        response = self.client.post(
            reverse("listing_apply", kwargs={"slug": self.property.slug}),
            {
                "full_name": "Applicant One",
                "email": "applicant@example.test",
                "phone": "92000000",
                "occupants": 2,
                "unit": self.unit.id,
            },
        )
        self.assertRedirects(response, reverse("listing_detail", kwargs={"slug": self.property.slug}))
        application = Application.objects.get(email="applicant@example.test")
        self.assertEqual(application.unit, self.unit)
        self.assertEqual(application.unit_type, self.unit_type)
        self.assertEqual(application.rental_amount, Decimal("600.000"))

# Create your tests here.
