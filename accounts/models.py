import secrets
import hashlib
import json
import re

from django.conf import settings
from django.contrib.auth.models import Group
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class UserProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="pms_profile")
    phone = models.CharField(max_length=30, blank=True)
    preferred_language = models.CharField(max_length=10, default="en")
    timezone = models.CharField(max_length=64, default="Asia/Muscat")
    email_verified_at = models.DateTimeField(null=True, blank=True)
    two_factor_enabled = models.BooleanField(default=False)
    two_factor_secret = models.CharField(max_length=255, blank=True)
    force_password_change = models.BooleanField(default=False)
    security_updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.user.get_full_name() or self.user.get_username()


class PropertyAccess(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="property_access")
    property = models.ForeignKey("properties.Property", on_delete=models.CASCADE, related_name="staff_access")
    group = models.ForeignKey(Group, on_delete=models.PROTECT, related_name="property_access")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("user", "property"), name="unique_user_property_access")]
        verbose_name_plural = "property access"

    def __str__(self):
        return f"{self.user} · {self.property} · {self.group}"


class Invitation(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        ACCEPTED = "accepted", _("Accepted")
        REVOKED = "revoked", _("Revoked")
        EXPIRED = "expired", _("Expired")

    email = models.EmailField()
    token = models.CharField(max_length=64, unique=True, default=secrets.token_urlsafe)
    group = models.ForeignKey(Group, on_delete=models.PROTECT)
    scope_property = models.ForeignKey("properties.Property", on_delete=models.CASCADE, null=True, blank=True)
    invited_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="sent_invitations")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def is_usable(self):
        return self.status == self.Status.PENDING and self.expires_at > timezone.now()

    def __str__(self):
        return self.email

    @staticmethod
    def digest(raw_token):
        return hashlib.sha256(raw_token.encode()).hexdigest()

    def issue_token(self):
        raw_token = secrets.token_urlsafe(32)
        self.token = self.digest(raw_token)
        return raw_token

    def save(self, *args, **kwargs):
        if self.token and not re.fullmatch(r"[0-9a-f]{64}", self.token):
            self.token = self.digest(self.token)
        return super().save(*args, **kwargs)


class Capability(models.Model):
    name = models.CharField(max_length=120, unique=True)
    label = models.CharField(max_length=120)
    description = models.CharField(max_length=255)
    groups = models.ManyToManyField(Group, blank=True, related_name="pms_capabilities")

    class Meta:
        ordering = ("name",)
        verbose_name_plural = "capabilities"

    def __str__(self):
        return self.name


class GroupProfile(models.Model):
    group = models.OneToOneField(Group, on_delete=models.CASCADE, related_name="pms_profile")
    label = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    color = models.CharField(max_length=7, default="#087a78")
    is_system = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.label


class Passkey(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="passkeys")
    name = models.CharField(max_length=100)
    credential_id = models.BinaryField(unique=True)
    public_key = models.BinaryField()
    sign_count = models.PositiveBigIntegerField(default=0)
    last_used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user} · {self.name}"


class RecoveryCode(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="recovery_codes")
    code_hash = models.CharField(max_length=128)
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("user", "code_hash"), name="unique_user_recovery_code")]


class EmailVerificationToken(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="email_verification_tokens")
    token_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def is_usable(self):
        return self.used_at is None and self.expires_at > timezone.now()


class AppSetting(models.Model):
    class ValueType(models.TextChoices):
        STRING = "string", _("String")
        BOOLEAN = "boolean", _("Boolean")
        INTEGER = "integer", _("Integer")
        JSON = "json", _("JSON")
        SECRET = "secret", _("Encrypted secret")

    group = models.CharField(max_length=50, default="general")
    key = models.CharField(max_length=120, unique=True)
    value = models.JSONField(default=dict, blank=True)
    value_type = models.CharField(max_length=10, choices=ValueType.choices, default=ValueType.JSON)
    is_secret = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("group", "key")

    def __str__(self):
        return self.key

    def set_value(self, value):
        if self.is_secret or self.value_type == self.ValueType.SECRET:
            from .security import encrypt
            self.value = {"encrypted": encrypt(json.dumps(value))}
            self.is_secret = True
            self.value_type = self.ValueType.SECRET
        else:
            self.value = {"value": value}

    def get_value(self, default=None):
        if self.is_secret or self.value_type == self.ValueType.SECRET:
            from .security import decrypt
            encrypted = self.value.get("encrypted")
            return json.loads(decrypt(encrypted)) if encrypted else default
        return self.value.get("value", default)

    def save(self, *args, **kwargs):
        if (self.is_secret or self.value_type == self.ValueType.SECRET) and "encrypted" not in self.value:
            self.set_value(self.value.get("value", self.value))
        return super().save(*args, **kwargs)


class AuditLog(models.Model):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    action = models.CharField(max_length=80)
    target_type = models.CharField(max_length=120, blank=True)
    target_id = models.CharField(max_length=80, blank=True)
    summary = models.CharField(max_length=255)
    changes = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.action}: {self.summary}"

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValueError(_("Audit logs are immutable."))
        return super().save(*args, **kwargs)

# Create your models here.
