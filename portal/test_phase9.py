from decimal import Decimal
import tempfile

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.test import TestCase
from django.urls import reverse

from properties.models import Property, PropertyMedia, Tenant, Unit, UnitType, UnitTypeRate

from .models import Application
from .services import convert_application, submit_application, transition_application


class ApplicationWorkflowTests(TestCase):
    def setUp(self):
        self.media_root = tempfile.TemporaryDirectory()
        self.override = override_settings(MEDIA_ROOT=self.media_root.name)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.addCleanup(self.media_root.cleanup)
        self.staff = get_user_model().objects.create_superuser("reviewer", "reviewer@example.test", "password")
        self.property = Property.objects.create(
            name="Published Residence",
            public_slug="published-residence",
            address="Muscat",
            description="A complete public listing.",
            is_public=True,
            is_published=True,
        )
        self.unit_type = UnitType.objects.create(
            property=self.property,
            name="One bedroom",
            public_slug="one-bedroom",
            is_published=True,
        )
        self.unit = Unit.objects.create(
            property=self.property,
            unit_type=self.unit_type,
            name="101",
            monthly_rent=Decimal("450.000"),
            status=Unit.Status.AVAILABLE,
        )
        UnitTypeRate.objects.create(unit_type=self.unit_type, amount=Decimal("450.000"))
        self.data = {
            "full_name": "Applicant",
            "email": "applicant@example.test",
            "phone": "92000000",
            "occupants": 1,
        }

    def submit(self):
        return submit_application(
            property_obj=self.property,
            unit_type=self.unit_type,
            unit=self.unit,
            **self.data,
        )

    def test_only_publication_ready_properties_are_visible(self):
        hidden = Property.objects.create(
            name="Incomplete",
            address="Muscat",
            is_public=True,
            is_published=True,
        )
        response = self.client.get(reverse("listing_index"))
        self.assertContains(response, self.property.name)
        self.assertNotContains(response, hidden.name)
        self.assertEqual(self.client.get(reverse("listing_detail", kwargs={"slug": hidden.slug})).status_code, 404)

    def test_submission_snapshots_offer_and_prevents_duplicate_open_application(self):
        application = self.submit()
        self.assertEqual(application.rental_amount, Decimal("450.000"))
        self.assertEqual(application.rental_currency, "OMR")
        with self.assertRaisesMessage(ValidationError, "already have an open application"):
            self.submit()

    def test_strict_review_lifecycle_and_reapplication_after_terminal_status(self):
        application = self.submit()
        with self.assertRaises(ValidationError):
            transition_application(application, Application.Status.ACCEPTED, actor=self.staff)
        application = transition_application(application, Application.Status.REVIEWING, actor=self.staff)
        application = transition_application(
            application,
            Application.Status.REJECTED,
            actor=self.staff,
            applicant_feedback="The offering is no longer available.",
        )
        self.assertIsNone(application.open_application_key)
        self.assertEqual(self.submit().status, Application.Status.NEW)

    def test_accepted_application_conversion_is_idempotent(self):
        application = transition_application(self.submit(), Application.Status.REVIEWING, actor=self.staff)
        application = transition_application(application, Application.Status.ACCEPTED, actor=self.staff)
        tenant = convert_application(application, actor=self.staff)
        self.assertEqual(convert_application(application, actor=self.staff), tenant)
        self.assertEqual(Tenant.objects.filter(email=self.data["email"]).count(), 1)

    def test_staff_review_workspace_and_seo_metadata(self):
        application = self.submit()
        self.client.force_login(self.staff)
        self.assertContains(self.client.get(reverse("application_list")), self.data["full_name"])
        self.assertContains(
            self.client.get(reverse("application_workspace", kwargs={"application_id": application.pk})),
            "Rental offer snapshot",
        )
        self.client.logout()
        response = self.client.get(reverse("listing_detail", kwargs={"slug": self.property.public_slug}))
        self.assertContains(response, '<meta name="description"', html=False)
        self.assertContains(response, '<link rel="canonical"', html=False)

    def test_only_published_gallery_media_is_delivered(self):
        media = PropertyMedia.objects.create(
            property=self.property,
            file=SimpleUploadedFile("home.jpg", b"public-image", content_type="image/jpeg"),
            is_public=True,
        )
        response = self.client.get(reverse("public_listing_media", kwargs={"media_id": media.pk}))
        self.assertEqual(response.status_code, 200)
        media.is_public = False
        media.save(update_fields=("is_public",))
        self.assertEqual(self.client.get(reverse("public_listing_media", kwargs={"media_id": media.pk})).status_code, 404)

    def test_applicant_can_withdraw_but_cannot_make_review_decisions(self):
        applicant = get_user_model().objects.create_user("applicant", password="password")
        application = submit_application(
            user=applicant,
            property_obj=self.property,
            unit_type=self.unit_type,
            unit=self.unit,
            **self.data,
        )
        with self.assertRaises(ValidationError):
            transition_application(application, Application.Status.REVIEWING, actor=applicant, applicant=True)
        application = transition_application(application, Application.Status.WITHDRAWN, actor=applicant, applicant=True)
        self.assertEqual(application.status, Application.Status.WITHDRAWN)
