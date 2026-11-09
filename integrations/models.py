from django.db import models
from django.utils.translation import gettext_lazy as _


class Integration(models.Model):
    class Kind(models.TextChoices):
        PAYMENT = "payment", _("Payment gateway")
        EMAIL = "email", _("Email")
        WHATSAPP = "whatsapp", _("WhatsApp")
        STORAGE = "storage", _("Storage")
        PLUGIN = "plugin", _("Plugin")

    name = models.CharField(max_length=120, unique=True)
    kind = models.CharField(max_length=20, choices=Kind.choices)
    provider = models.CharField(max_length=100)
    configuration = models.JSONField(default=dict, blank=True)
    secret_reference = models.CharField(max_length=255, blank=True, help_text=_("Path or environment variable name; never store a secret value here."))
    is_enabled = models.BooleanField(default=False)
    last_health_check_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("kind", "name")

    def __str__(self):
        return self.name


class ExtensionHook(models.Model):
    integration = models.ForeignKey(Integration, on_delete=models.CASCADE, related_name="hooks")
    event = models.CharField(max_length=120)
    endpoint = models.URLField()
    is_enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("integration", "event", "endpoint"), name="unique_extension_hook")]


class IntegrationEvent(models.Model):
    integration = models.ForeignKey(Integration, on_delete=models.CASCADE, related_name="events")
    event = models.CharField(max_length=120)
    payload = models.JSONField(default=dict)
    status = models.CharField(max_length=30, default="pending")
    attempts = models.PositiveSmallIntegerField(default=0)
    next_attempt_at = models.DateTimeField(null=True, blank=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)


class ExtensionInstallation(models.Model):
    class Status(models.TextChoices):
        READY = "ready", _("Ready")
        DISABLED = "disabled", _("Disabled")
        INCOMPATIBLE = "incompatible", _("Incompatible")
        DEGRADED = "degraded", _("Degraded")

    slug = models.SlugField(max_length=120, unique=True)
    name = models.CharField(max_length=160)
    version = models.CharField(max_length=40)
    description = models.TextField(blank=True)
    dependencies = models.JSONField(default=dict, blank=True)
    is_enabled = models.BooleanField(default=True)
    is_system = models.BooleanField(default=False)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.READY)
    last_error = models.TextField(blank=True)
    discovered_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name",)

    def __str__(self):
        return f"{self.name} {self.version}"

# Create your models here.
