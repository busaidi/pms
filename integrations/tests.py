from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import AppSetting, Capability

from .models import ExtensionInstallation, Integration
from .registry import ExtensionManifest, discover_extensions, dispatch_event, extension_states, register_manifest, registries, unregister_manifest
from .services import save_secret, synchronize_extensions, test_integration as run_integration_test


class ExtensionRegistryTests(TestCase):
    def test_reference_extension_exercises_every_registry_and_event_listener(self):
        states = discover_extensions()
        self.assertEqual(states["reference-extension"]["status"], "ready")
        for count in registries.counts().values():
            self.assertGreaterEqual(count, 1)
        result = dispatch_event("reference.ping", {"value": 3})
        self.assertTrue(result[0]["received"])
        self.assertEqual(result[0]["payload"], {"value": 3})

    def test_dependency_validation_marks_incompatible_extension(self):
        slug = "missing-dependency-probe"
        try:
            register_manifest(ExtensionManifest(slug=slug, name="Missing dependency probe", version="1.0.0", dependencies={"not-installed": "1.0.0"}, register=lambda context: None))
            discover_extensions()
            self.assertEqual(extension_states()[slug]["status"], "incompatible")
            self.assertIn("Missing dependency", extension_states()[slug]["error"])
        finally:
            unregister_manifest(slug)
            discover_extensions()


class IntegrationManagementTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("extension-admin", "admin@example.test", "password")
        self.client.force_login(self.admin)

    def test_sync_persists_extension_status_and_permission(self):
        synchronize_extensions()
        extension = ExtensionInstallation.objects.get(slug="reference-extension")
        self.assertEqual(extension.status, ExtensionInstallation.Status.READY)
        self.assertTrue(extension.is_system)
        self.assertTrue(Capability.objects.filter(name="reference-extension.view").exists())

    def test_secret_configuration_is_encrypted_and_not_in_integration_json(self):
        integration = Integration.objects.create(name="WhatsApp log", kind=Integration.Kind.WHATSAPP, provider="log", configuration={"sender": "demo"})
        setting = save_secret(integration, "api_token", "top-secret-token")
        setting.refresh_from_db()
        self.assertNotIn("top-secret-token", str(setting.value))
        self.assertEqual(setting.get_value(), "top-secret-token")
        integration.refresh_from_db()
        self.assertEqual(integration.secret_reference, setting.key)

    def test_configuration_rejects_secrets_in_plain_json(self):
        response = self.client.post(reverse("integration_create"), {
            "name": "Unsafe", "kind": Integration.Kind.WHATSAPP, "provider": "log", "is_enabled": "on",
            "configuration": '{"api_token": "plaintext"}',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Move secret values")
        self.assertFalse(Integration.objects.filter(name="Unsafe").exists())

    def test_provider_health_success_and_failure_are_recorded(self):
        working = Integration.objects.create(name="Manual payment", kind=Integration.Kind.PAYMENT, provider="manual", is_enabled=True)
        broken = Integration.objects.create(name="Missing WhatsApp", kind=Integration.Kind.WHATSAPP, provider="not-installed", is_enabled=True)
        self.assertTrue(run_integration_test(working)[0])
        self.assertFalse(run_integration_test(broken, "92000000")[0])
        working.refresh_from_db(); broken.refresh_from_db()
        self.assertIsNotNone(working.last_health_check_at)
        self.assertIn("not installed", broken.last_error)

    def test_management_ui_and_health_probe(self):
        Integration.objects.create(name="Manual payment", kind=Integration.Kind.PAYMENT, provider="manual", is_enabled=True)
        response = self.client.get(reverse("integration_list"))
        self.assertContains(response, "Reference extension")
        self.assertContains(response, "Manual payment")
        response = self.client.get(reverse("reference_extension_probe"))
        self.assertContains(response, "Event listener result")
        response = self.client.get(reverse("extension_health"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    def test_dedicated_mail_settings_store_password_encrypted(self):
        response = self.client.post(reverse("mail_settings"), {"provider": "smtp", "is_enabled": "on", "host": "smtp.example.test", "port": 587, "username": "mailer", "password": "mail-secret", "from_email": "noreply@example.test", "use_tls": "on", "timeout": 10})
        self.assertRedirects(response, reverse("mail_settings"))
        integration = Integration.objects.get(kind=Integration.Kind.EMAIL)
        self.assertNotIn("mail-secret", str(integration.configuration))
        self.assertEqual(AppSetting.objects.get(key=integration.secret_reference).get_value(), "mail-secret")

    @override_settings(DEBUG=True)
    def test_whatsapp_log_provider_can_send_test(self):
        saved = self.client.post(reverse("whatsapp_settings"), {"provider": "log", "is_enabled": "on", "endpoint": "", "sender": "Oman Skylight", "api_token": ""})
        self.assertRedirects(saved, reverse("whatsapp_settings"))
        response = self.client.post(reverse("whatsapp_test"), {"recipient": "92000000"})
        self.assertRedirects(response, reverse("whatsapp_settings"))
        integration = Integration.objects.get(kind=Integration.Kind.WHATSAPP)
        self.assertEqual(integration.last_error, "")

    @override_settings(DEBUG=False, EMAIL_BACKEND="integrations.mail_backend.DatabaseEmailBackend")
    def test_console_mail_is_rejected_in_production(self):
        Integration.objects.create(name="Console email", kind=Integration.Kind.EMAIL, provider="console", is_enabled=True)
        with self.assertRaisesRegex(ValueError, "disabled in production"):
            send_mail("Subject", "Body", None, ["person@example.test"])

    @override_settings(DEBUG=False)
    def test_log_whatsapp_is_rejected_in_production(self):
        integration = Integration.objects.create(name="Log WhatsApp", kind=Integration.Kind.WHATSAPP, provider="log", is_enabled=True)
        ok, detail = run_integration_test(integration, "92000000")
        self.assertFalse(ok)
        self.assertIn("disabled in production", detail)
