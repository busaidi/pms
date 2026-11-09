from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.access import user_has_capability

from .forms import IntegrationForm, IntegrationTestForm, MailSettingsForm, WhatsAppSettingsForm
from .models import ExtensionInstallation, Integration
from .registry import dispatch_event, registries
from .services import save_secret, synchronize_extensions, test_integration
from django.utils.translation import gettext_lazy as _


def _require_settings(user):
    if not user_has_capability(user, "roles.update"):
        raise PermissionDenied


@login_required
def integration_list(request):
    _require_settings(request.user)
    extensions = synchronize_extensions()
    return render(request, "integrations/list.html", {"integrations": Integration.objects.all(), "extensions": extensions, "registry_counts": registries.counts()})


def _provider_initial(kind, defaults):
    integration = Integration.objects.filter(kind=kind).order_by("pk").first()
    if not integration:
        return None, defaults
    return integration, {**defaults, **integration.configuration, "provider": integration.provider, "is_enabled": integration.is_enabled}


@login_required
def mail_settings(request):
    _require_settings(request.user)
    integration, initial = _provider_initial(Integration.Kind.EMAIL, {"provider": "smtp", "port": 587, "use_tls": True, "from_email": "noreply@omanskylight.com", "timeout": 10})
    form = MailSettingsForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        integration, _created = Integration.objects.update_or_create(
            pk=integration.pk if integration else None,
            defaults={"name": "Application email", "kind": Integration.Kind.EMAIL, "provider": data["provider"], "is_enabled": data["is_enabled"], "configuration": {key: data[key] for key in ("host", "port", "username", "from_email", "use_tls", "use_ssl", "timeout")}},
        )
        if data.get("password"):
            save_secret(integration, "password", data["password"])
        messages.success(request, _("Mail settings saved."))
        return redirect("mail_settings")
    return render(request, "integrations/provider_settings.html", {"form": form, "title": _("Mail settings"), "kind": "mail", "integration": integration})


@login_required
@require_POST
def mail_test(request):
    _require_settings(request.user)
    integration = get_object_or_404(Integration, kind=Integration.Kind.EMAIL)
    ok, detail = test_integration(integration, request.POST.get("recipient", ""))
    (messages.success if ok else messages.error)(request, detail)
    return redirect("mail_settings")


@login_required
def whatsapp_settings(request):
    _require_settings(request.user)
    integration, initial = _provider_initial(Integration.Kind.WHATSAPP, {"provider": "webhook"})
    form = WhatsAppSettingsForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        integration, _created = Integration.objects.update_or_create(
            pk=integration.pk if integration else None,
            defaults={"name": "WhatsApp messaging", "kind": Integration.Kind.WHATSAPP, "provider": data["provider"], "is_enabled": data["is_enabled"], "configuration": {"endpoint": data["endpoint"], "sender": data["sender"]}},
        )
        if data.get("api_token"):
            save_secret(integration, "api_token", data["api_token"])
        messages.success(request, _("WhatsApp settings saved."))
        return redirect("whatsapp_settings")
    return render(request, "integrations/provider_settings.html", {"form": form, "title": _("WhatsApp settings"), "kind": "whatsapp", "integration": integration})


@login_required
@require_POST
def whatsapp_test(request):
    _require_settings(request.user)
    integration = get_object_or_404(Integration, kind=Integration.Kind.WHATSAPP)
    ok, detail = test_integration(integration, request.POST.get("recipient", ""))
    (messages.success if ok else messages.error)(request, detail)
    return redirect("whatsapp_settings")


@login_required
def integration_edit(request, integration_id=None):
    _require_settings(request.user)
    integration = get_object_or_404(Integration, pk=integration_id) if integration_id else None
    form = IntegrationForm(request.POST or None, instance=integration)
    if request.method == "POST" and form.is_valid():
        integration = form.save()
        token = form.cleaned_data.get("api_token")
        if token:
            save_secret(integration, "api_token", token)
        messages.success(request, _("Integration settings saved."))
        return redirect("integration_list")
    return render(request, "properties/form.html", {"form": form, "title": "Edit integration" if integration else "Add integration", "eyebrow": "Integrations"})


@login_required
@require_POST
def integration_test(request, integration_id):
    _require_settings(request.user)
    integration = get_object_or_404(Integration, pk=integration_id)
    form = IntegrationTestForm(request.POST)
    if form.is_valid():
        ok, detail = test_integration(integration, form.cleaned_data["recipient"])
        (messages.success if ok else messages.error)(request, detail)
    return redirect("integration_list")


@login_required
@require_POST
def extension_toggle(request, extension_id):
    _require_settings(request.user)
    extension = get_object_or_404(ExtensionInstallation, pk=extension_id)
    if extension.is_system:
        messages.error(request, _("System extensions cannot be disabled."))
    else:
        extension.is_enabled = not extension.is_enabled
        extension.status = ExtensionInstallation.Status.READY if extension.is_enabled else ExtensionInstallation.Status.DISABLED
        extension.save(update_fields=("is_enabled", "status", "updated_at"))
        messages.success(request, _("%(extension)s is %(status)s.") % {"extension": extension.name, "status": _("enabled") if extension.is_enabled else _("disabled")})
    return redirect("integration_list")


@login_required
def reference_extension_probe(request):
    _require_settings(request.user)
    results = dispatch_event("reference.ping", {"actor": request.user.pk})
    return render(request, "integrations/reference_probe.html", {"registry_counts": registries.counts(), "event_results": results})


@login_required
def extension_health(request):
    _require_settings(request.user)
    extensions = synchronize_extensions()
    healthy = all(item.status in (ExtensionInstallation.Status.READY, ExtensionInstallation.Status.DISABLED) for item in extensions)
    return JsonResponse({"status": "ok" if healthy else "degraded", "registries": registries.counts(), "extensions": [{"slug": item.slug, "status": item.status, "version": item.version} for item in extensions]}, status=200 if healthy else 503)

# Create your views here.
