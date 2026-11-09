from datetime import date, timedelta
from decimal import Decimal
import json
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils.translation import override

from properties.models import Lease, Property, Tenant, Unit
from accounts.models import PropertyAccess
from tools.build_ar_locale import CATALOG, collect_messages


class DashboardTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("manager", password="safe-test-pass", is_superuser=True)

    def test_anonymous_user_is_sent_to_login(self):
        response = self.client.get(reverse("dashboard"))

        self.assertRedirects(response, f"{reverse('login')}?next=/")

    def test_dashboard_calculates_live_portfolio_metrics(self):
        building = Property.objects.create(name="Al Mouj Waves", address="Al Mouj")
        occupied = Unit.objects.create(
            property=building,
            name="A-101",
            monthly_rent=Decimal("725.000"),
            status=Unit.Status.OCCUPIED,
        )
        Unit.objects.create(
            property=building,
            name="A-102",
            monthly_rent=Decimal("700.000"),
            status=Unit.Status.AVAILABLE,
        )
        tenant = Tenant.objects.create(full_name="Salim Al Harthy", phone="90000000")
        Lease.objects.create(
            unit=occupied,
            tenant=tenant,
            start_date=date.today(),
            end_date=date.today() + timedelta(days=365),
            monthly_rent=Decimal("725.000"),
            status=Lease.Status.ACTIVE,
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["occupancy"], 50)
        self.assertEqual(response.context["monthly_rent"], Decimal("725.000"))
        self.assertContains(response, "Al Mouj Waves")

    def test_global_search_returns_scoped_business_records(self):
        building = Property.objects.create(name="Atheer", address="Muscat")
        Unit.objects.create(property=building, name="Flat 41", monthly_rent=Decimal("400.000"))
        self.client.force_login(self.user)
        response = self.client.get(reverse("global_search"), {"q": "Atheer"})
        self.assertContains(response, "Atheer")
        self.assertContains(response, reverse("property_workspace", args=(building.slug,)))

    def test_dashboard_metrics_respect_property_assignment(self):
        call_command("sync_roles", verbosity=0)
        visible = Property.objects.create(name="Alpha Visible", address="Muscat")
        hidden = Property.objects.create(name="Alpha Hidden", address="Muscat")
        Unit.objects.create(property=visible, name="V-1", monthly_rent=Decimal("100.000"))
        Unit.objects.create(property=hidden, name="H-1", monthly_rent=Decimal("200.000"))
        scoped = get_user_model().objects.create_user("scoped-dashboard", password="safe-test-pass")
        PropertyAccess.objects.create(user=scoped, property=visible, group=Group.objects.get(name="property-manager"))
        self.client.force_login(scoped)
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total_units"], 1)
        self.assertContains(response, "Alpha Visible")
        self.assertNotContains(response, "Alpha Hidden")
        search = self.client.get(reverse("global_search"), {"q": "Alpha"})
        self.assertContains(search, "Alpha Visible")
        self.assertNotContains(search, "Alpha Hidden")


class NavigationStateTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            "navigation-admin", "navigation@example.test", "safe-test-pass"
        )
        self.client.force_login(self.user)

    def test_sidebar_highlights_each_current_section(self):
        routes = {
            "dashboard": "overview",
            "property_list": "properties",
            "tenant_list": "tenants",
            "application_list": "applications",
            "lease_list": "leases",
            "invoice_list": "invoices",
            "payment_list": "payments",
            "financial_dashboard": "financial-reports",
            "maintenance_list": "maintenance",
            "expense_list": "expenses",
            "utility_list": "utilities",
            "inspection_list": "inspections",
            "team": "team",
            "roles": "roles",
            "integration_list": "integrations",
            "settings_general": "integrations",
            "payment_gateway_settings": "integrations",
            "account_profile": "account",
        }

        for route_name, expected_section in routes.items():
            with self.subTest(route_name=route_name):
                response = self.client.get(reverse(route_name))
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context["active_navigation"], expected_section)
                self.assertEqual(
                    response.content.count(b'class="nav-item active"'),
                    0 if route_name == "account_profile" else 1,
                )
                self.assertContains(response, 'aria-current="page"', count=1)

    def test_account_actions_are_only_in_topbar_menu(self):
        response = self.client.get(reverse("dashboard"))

        self.assertContains(response, "data-user-menu-trigger")
        self.assertContains(response, "data-user-menu-panel")
        self.assertContains(response, f'href="{reverse("account_profile")}"', count=1)
        self.assertContains(response, f'action="{reverse("logout")}"', count=1)
        self.assertNotContains(response, ">My account</span></a>")

    def test_detail_page_keeps_parent_navigation_item_active(self):
        property_obj = Property.objects.create(name="Navigation House", address="Muscat")

        response = self.client.get(reverse("property_workspace", args=(property_obj.slug,)))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["active_navigation"], "properties")
        self.assertContains(
            response,
            f'class="nav-item active" href="{reverse("property_list")}" aria-current="page"',
        )


class HealthTests(TestCase):
    @patch("core.views.Redis.from_url")
    def test_health_reports_database_and_redis_state(self, redis_from_url):
        redis_from_url.return_value.ping.return_value = True
        response = self.client.get(reverse("health"))
        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(response.content, {"status": "ok", "checks": {"database": True, "redis": True}})


class LocalizationTests(TestCase):
    def test_language_switch_persists_arabic_choice(self):
        response = self.client.post(
            reverse("set_language"),
            {"language": "ar", "next": reverse("listing_index")},
        )

        self.assertRedirects(response, reverse("listing_index"), fetch_redirect_response=False)
        self.assertEqual(response.cookies[settings.LANGUAGE_COOKIE_NAME].value, "ar")

    def test_authenticated_language_switch_updates_profile(self):
        from accounts.models import UserProfile

        user = get_user_model().objects.create_user("arabic-user", password="safe-test-pass")
        self.client.force_login(user)
        response = self.client.post(
            reverse("set_language"),
            {"language": "ar", "next": reverse("dashboard")},
        )

        self.assertEqual(response.cookies[settings.LANGUAGE_COOKIE_NAME].value, "ar")
        self.assertEqual(UserProfile.objects.get(user=user).preferred_language, "ar")

    def test_arabic_public_page_uses_rtl_and_translated_copy(self):
        response = self.client.get(reverse("listing_index"), HTTP_ACCEPT_LANGUAGE="ar")

        self.assertContains(response, '<html lang="ar" dir="rtl">')
        self.assertContains(response, "استكشف عقاراتنا")
        self.assertNotContains(response, ">العربية</button>")
        self.assertContains(response, "English")

    def test_model_choices_and_form_labels_translate(self):
        from accounts.forms import ProfileForm

        with override("ar"):
            form = ProfileForm()
            self.assertEqual(str(Property.RentalMode.WHOLE.label), "العقار بأكمله")
            self.assertEqual(str(form.fields["first_name"].label), "الاسم الأول")

    def test_arabic_catalog_covers_every_marked_message(self):
        translations = json.loads(CATALOG.read_text(encoding="utf-8"))

        self.assertEqual(set(translations), set(collect_messages()))
        self.assertTrue(all(value.strip() for value in translations.values()))

# Create your tests here.
