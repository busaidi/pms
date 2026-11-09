import logging
import json
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

from accounts.models import AppSetting, Capability

from .models import ExtensionInstallation, Integration
from .registry import discover_extensions, extension_manifests, extension_states, registries
from django.utils.translation import gettext_lazy as _


logger = logging.getLogger(__name__)


def synchronize_extensions():
    states = discover_extensions()
    manifests = extension_manifests()
    installations = []
    for slug, manifest in manifests.items():
        state = states.get(slug, {"status": "degraded", "error": "Extension was not activated."})
        installation, _created = ExtensionInstallation.objects.update_or_create(
            slug=slug,
            defaults={
                "name": manifest.name,
                "version": manifest.version,
                "description": manifest.description,
                "dependencies": manifest.dependencies,
                "is_system": manifest.is_system,
                "status": state["status"],
                "last_error": state["error"],
                "discovered_at": timezone.now(),
            },
        )
        if not installation.is_enabled:
            installation.status = ExtensionInstallation.Status.DISABLED
            installation.save(update_fields=("status", "updated_at"))
        installations.append(installation)
    for item in registries.permissions.all():
        value = item.value
        Capability.objects.update_or_create(
            name=item.key,
            defaults={"label": value.get("label", item.key), "description": value.get("description", "Extension permission")},
        )
    return installations


def save_secret(integration, name, value):
    key = f"integration.{integration.pk}.{name}"
    setting, _created = AppSetting.objects.get_or_create(
        key=key,
        defaults={"group": "integrations", "value_type": AppSetting.ValueType.SECRET, "is_secret": True},
    )
    setting.set_value(value)
    setting.save()
    integration.secret_reference = key
    integration.save(update_fields=("secret_reference", "updated_at"))
    return setting


def get_secret(integration):
    if not integration.secret_reference:
        return ""
    setting = AppSetting.objects.filter(key=integration.secret_reference).first()
    return setting.get_value() if setting else ""


def send_whatsapp(recipient, message, integration=None):
    integration = integration or Integration.objects.filter(kind=Integration.Kind.WHATSAPP, is_enabled=True).order_by("pk").first()
    if not integration:
        raise ValueError(_("WhatsApp integration is disabled or not configured."))
    if integration.provider == "log":
        if not settings.DEBUG:
            raise ValueError(_("The server log WhatsApp provider is disabled in production."))
        logger.info("WhatsApp to %s: %s", recipient, message)
        return {"provider": "log", "accepted": True}
    if integration.provider != "webhook":
        raise ValueError(_("WhatsApp provider %(provider)s is not installed on this server.") % {"provider": integration.provider})
    payload = json.dumps({"to": recipient, "message": message, "sender": integration.configuration.get("sender", "")}).encode()
    headers = {"Content-Type": "application/json"}
    token = get_secret(integration)
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(integration.configuration.get("endpoint", ""), data=payload, headers=headers, method="POST")
    with urlopen(request, timeout=10) as response:
        if response.status >= 400:
            raise ValueError(_("WhatsApp webhook rejected the message."))
        return {"provider": "webhook", "accepted": True, "status": response.status}


def test_integration(integration, recipient=""):
    try:
        if integration.kind == Integration.Kind.EMAIL:
            if not recipient:
                raise ValueError(_("A recipient email address is required."))
            send_mail("Oman Skylight integration test", "Your email integration is working.", settings.DEFAULT_FROM_EMAIL, [recipient], fail_silently=False)
        elif integration.kind == Integration.Kind.WHATSAPP:
            if not recipient:
                raise ValueError(_("A recipient phone number is required."))
            send_whatsapp(recipient, _("Your Oman Skylight WhatsApp integration is working."), integration)
        elif integration.kind == Integration.Kind.PAYMENT:
            if integration.provider != "manual":
                raise ValueError(
                    _("Payment provider %(provider)s is not installed on this server.")
                    % {"provider": integration.provider}
                )
        elif integration.kind == Integration.Kind.PLUGIN:
            installation = ExtensionInstallation.objects.filter(slug=integration.provider).first()
            if not installation or installation.status != ExtensionInstallation.Status.READY:
                raise ValueError(_("The extension is not ready."))
        integration.last_health_check_at = timezone.now()
        integration.last_error = ""
        integration.save(update_fields=("last_health_check_at", "last_error", "updated_at"))
        return True, "Health check passed."
    except Exception as error:
        integration.last_health_check_at = timezone.now()
        integration.last_error = str(error)
        integration.save(update_fields=("last_health_check_at", "last_error", "updated_at"))
        return False, str(error)
