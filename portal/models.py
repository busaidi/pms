import builtins

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class Application(models.Model):
    class Status(models.TextChoices):
        NEW = "new", _("New")
        REVIEWING = "reviewing", _("Reviewing")
        ACCEPTED = "accepted", _("Accepted")
        REJECTED = "rejected", _("Rejected")
        WITHDRAWN = "withdrawn", _("Withdrawn")

    class TargetType(models.TextChoices):
        WHOLE_PROPERTY = "whole_property", _("Whole property")
        UNIT_TYPE = "unit_type", _("Unit type")

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="rental_applications")
    property = models.ForeignKey("properties.Property", on_delete=models.PROTECT, related_name="applications")
    unit = models.ForeignKey("properties.Unit", on_delete=models.PROTECT, null=True, blank=True, related_name="applications")
    unit_type = models.ForeignKey("properties.UnitType", on_delete=models.PROTECT, null=True, blank=True, related_name="applications")
    target_type = models.CharField(max_length=20, choices=TargetType.choices, default=TargetType.UNIT_TYPE)
    full_name = models.CharField(max_length=160)
    email = models.EmailField()
    phone = models.CharField(max_length=30)
    nationality = models.CharField(max_length=80, blank=True)
    desired_move_in = models.DateField(null=True, blank=True)
    occupants = models.PositiveSmallIntegerField(default=1)
    monthly_income = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    message = models.TextField(blank=True)
    intended_move_in_timeframe = models.CharField(max_length=120, blank=True)
    rental_billing_unit = models.CharField(max_length=10, blank=True)
    rental_billing_interval = models.PositiveSmallIntegerField(null=True, blank=True)
    rental_currency = models.CharField(max_length=3, blank=True)
    rental_amount = models.DecimalField(max_digits=14, decimal_places=3, null=True, blank=True)
    operator_notes = models.TextField(blank=True)
    applicant_feedback = models.TextField(blank=True)
    open_application_key = models.CharField(max_length=255, unique=True, null=True, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.NEW)
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="assigned_applications")
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="reviewed_applications")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    converted_tenant = models.ForeignKey("properties.Tenant", on_delete=models.PROTECT, null=True, blank=True, related_name="source_applications")
    converted_at = models.DateTimeField(null=True, blank=True)
    submitted_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-submitted_at",)
        constraints = [models.CheckConstraint(condition=(models.Q(target_type="whole_property", unit_type__isnull=True) | models.Q(target_type="unit_type", unit_type__isnull=False)), name="application_target_matches_unit_type")]

    def __str__(self):
        return f"{self.full_name} · {self.property}"

    @builtins.property
    def is_open(self):
        return self.status in {self.Status.NEW, self.Status.REVIEWING}


class ApplicationDocument(models.Model):
    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name="documents")
    name = models.CharField(max_length=160)
    file = models.FileField(upload_to="applications/%Y/%m")
    created_at = models.DateTimeField(auto_now_add=True)


class PortalNotification(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="portal_notifications")
    title = models.CharField(max_length=160)
    message = models.TextField()
    url = models.CharField(max_length=255, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)


class SavedProperty(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="saved_properties")
    property = models.ForeignKey("properties.Property", on_delete=models.CASCADE, related_name="saved_by")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("user", "property"), name="unique_saved_property")]

# Create your models here.
