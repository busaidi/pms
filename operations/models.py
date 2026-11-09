import builtins

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class ExpenseCategory(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=120, unique=True, null=True, blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name_plural = "expense categories"
        ordering = ("sort_order", "name")

    def __str__(self):
        return self.name


class Expense(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", _("Active")
        VOIDED = "voided", _("Voided")

    property = models.ForeignKey("properties.Property", on_delete=models.PROTECT, related_name="expenses")
    category = models.ForeignKey(ExpenseCategory, on_delete=models.PROTECT, related_name="expenses")
    recurring_expense = models.ForeignKey("RecurringExpense", on_delete=models.PROTECT, null=True, blank=True, related_name="generated_expenses")
    amount = models.DecimalField(max_digits=12, decimal_places=3)
    currency = models.CharField(max_length=3, default="OMR")
    incurred_on = models.DateField()
    vendor = models.CharField(max_length=160, blank=True)
    description = models.TextField()
    notes = models.TextField(blank=True)
    reference = models.CharField(max_length=120, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    receipt = models.FileField(upload_to="expense-receipts/%Y/%m", blank=True, validators=[FileExtensionValidator(("jpg", "jpeg", "png", "webp", "pdf"))])
    receipt_original_name = models.CharField(max_length=255, blank=True)
    receipt_mime_type = models.CharField(max_length=120, blank=True)
    receipt_size = models.PositiveBigIntegerField(default=0)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_expenses")
    voided_at = models.DateTimeField(null=True, blank=True)
    voided_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="voided_expenses")
    void_reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-incurred_on", "-id")

    def __str__(self):
        return f"{self.property} · {self.currency} {self.amount}"

    def clean(self):
        self.currency = self.currency.upper()
        if self.amount <= 0:
            raise ValidationError({"amount": _("Expense amount must be positive.")})
        if len(self.currency) != 3 or not self.currency.isalpha():
            raise ValidationError({"currency": _("Use a three-letter ISO currency code.")})
        if self.status == self.Status.VOIDED and not self.void_reason.strip():
            raise ValidationError({"void_reason": _("A reason is required to void an expense.")})


class RecurringExpense(models.Model):
    class Frequency(models.TextChoices):
        DAILY = "daily", _("Daily")
        WEEKLY = "weekly", _("Weekly")
        MONTHLY = "monthly", _("Monthly")
        QUARTERLY = "quarterly", _("Quarterly")
        YEARLY = "yearly", _("Yearly")

    class BillingUnit(models.TextChoices):
        DAY = "day", _("Day")
        WEEK = "week", _("Week")
        MONTH = "month", _("Month")
        YEAR = "year", _("Year")

    property = models.ForeignKey("properties.Property", on_delete=models.CASCADE, related_name="recurring_expenses")
    category = models.ForeignKey(ExpenseCategory, on_delete=models.PROTECT)
    amount = models.DecimalField(max_digits=12, decimal_places=3)
    currency = models.CharField(max_length=3, default="OMR")
    vendor = models.CharField(max_length=160, blank=True)
    description = models.CharField(max_length=255)
    notes = models.TextField(blank=True)
    frequency = models.CharField(max_length=12, choices=Frequency.choices, default=Frequency.MONTHLY)
    billing_interval = models.PositiveSmallIntegerField(default=1)
    billing_unit = models.CharField(max_length=10, choices=BillingUnit.choices, default=BillingUnit.MONTH)
    start_date = models.DateField(default=timezone.localdate)
    next_run_on = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    is_paused = models.BooleanField(default=False)
    paused_at = models.DateTimeField(null=True, blank=True)
    ends_on = models.DateField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_recurring_expenses")
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.description

    def clean(self):
        self.currency = self.currency.upper()
        if self.amount <= 0:
            raise ValidationError({"amount": _("Expense amount must be positive.")})
        if self.billing_interval < 1:
            raise ValidationError({"billing_interval": _("Interval must be at least one.")})
        if self.ends_on and self.ends_on < self.start_date:
            raise ValidationError({"ends_on": _("End date cannot be before the start date.")})

    @builtins.property
    def schedule_status(self):
        if self.ends_on and (self.ends_on < timezone.localdate() or self.next_run_on is None):
            return "ended"
        return "active" if self.is_active and not self.is_paused else "paused"


class MaintenanceTicket(models.Model):
    class Status(models.TextChoices):
        REPORTED = "reported", _("Reported")
        IN_PROGRESS = "in_progress", _("In progress")
        RESOLVED = "resolved", _("Resolved")
        CANCELLED = "cancelled", _("Cancelled")

    class Priority(models.TextChoices):
        LOW = "low", _("Low")
        MEDIUM = "medium", _("Medium")
        HIGH = "high", _("High")
        URGENT = "urgent", _("Urgent")

    property = models.ForeignKey("properties.Property", on_delete=models.CASCADE, related_name="maintenance_tickets")
    unit = models.ForeignKey("properties.Unit", on_delete=models.SET_NULL, null=True, blank=True, related_name="maintenance_tickets")
    tenant = models.ForeignKey("properties.Tenant", on_delete=models.SET_NULL, null=True, blank=True, related_name="maintenance_tickets")
    reference = models.CharField(max_length=32, unique=True, null=True, blank=True)
    location = models.CharField(max_length=255, blank=True)
    title = models.CharField(max_length=180)
    description = models.TextField()
    status = models.CharField(max_length=14, choices=Status.choices, default=Status.REPORTED)
    priority = models.CharField(max_length=10, choices=Priority.choices, default=Priority.MEDIUM)
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="assigned_tickets")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_maintenance_tickets")
    estimated_cost = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    actual_cost = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    cost = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    blocks_unit = models.BooleanField(default=False)
    unit_status_before_block = models.CharField(max_length=20, blank=True)
    scheduled_for = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolution_notes = models.TextField(blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.reference or 'Ticket'} · {self.title}"

    def clean(self):
        if self.unit_id and self.unit.property_id != self.property_id:
            raise ValidationError({"unit": _("The unit must belong to the selected property.")})
        if self.status == self.Status.RESOLVED and not self.resolution_notes.strip():
            raise ValidationError({"resolution_notes": _("Resolution notes are required to resolve a ticket.")})
        if self.status == self.Status.CANCELLED and not self.cancellation_reason.strip():
            raise ValidationError({"cancellation_reason": _("A reason is required to cancel a ticket.")})

    def save(self, *args, **kwargs):
        if not self.reference:
            year = timezone.localdate().year
            prefix = f"TKT{year}"
            last = MaintenanceTicket.objects.filter(reference__startswith=prefix).order_by("-reference").values_list("reference", flat=True).first()
            number = int(last[len(prefix):]) + 1 if last else 1
            self.reference = f"{prefix}{number:04d}"
        super().save(*args, **kwargs)


class MaintenanceAttachment(models.Model):
    ticket = models.ForeignKey(MaintenanceTicket, on_delete=models.CASCADE, related_name="attachments")
    file = models.FileField(upload_to="maintenance/%Y/%m", validators=[FileExtensionValidator(("jpg", "jpeg", "png", "webp", "pdf", "doc", "docx"))])
    original_name = models.CharField(max_length=255, blank=True)
    mime_type = models.CharField(max_length=120, blank=True)
    size = models.PositiveBigIntegerField(default=0)
    caption = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class MaintenanceStatusHistory(models.Model):
    ticket = models.ForeignKey(MaintenanceTicket, on_delete=models.CASCADE, related_name="history")
    from_status = models.CharField(max_length=14, blank=True)
    to_status = models.CharField(max_length=14, choices=MaintenanceTicket.Status.choices)
    notes = models.TextField(blank=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at", "-id")


class UtilityMeter(models.Model):
    class Kind(models.TextChoices):
        ELECTRICITY = "electricity", _("Electricity")
        WATER = "water", _("Water")
        CUSTOM = "custom", _("Custom")
        GAS = "gas", _("Gas (legacy)")
        OTHER = "other", _("Other (legacy)")

    unit = models.ForeignKey("properties.Unit", on_delete=models.CASCADE, related_name="utility_meters")
    kind = models.CharField(max_length=16, choices=Kind.choices)
    serial_number = models.CharField(max_length=100)
    utility_name = models.CharField(max_length=100, blank=True)
    unit_of_measure = models.CharField(max_length=20, default="kWh")
    rate = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    currency = models.CharField(max_length=3, default="OMR")
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("unit", "serial_number"), name="unique_unit_meter_serial")]

    def __str__(self):
        return f"{self.unit} · {self.get_kind_display()}"

    def clean(self):
        self.currency = self.currency.upper()
        if self.kind == self.Kind.CUSTOM and not self.utility_name.strip():
            raise ValidationError({"utility_name": _("Enter a name for a custom utility.")})
        if self.kind != self.Kind.CUSTOM:
            self.utility_name = ""
        if self.rate < 0:
            raise ValidationError({"rate": _("Rate cannot be negative.")})


class UtilityReading(models.Model):
    class Kind(models.TextChoices):
        READING = "reading", _("Reading")
        ADJUSTMENT = "adjustment", _("Adjustment")

    meter = models.ForeignKey(UtilityMeter, on_delete=models.CASCADE, related_name="readings")
    read_at = models.DateTimeField()
    value = models.DecimalField(max_digits=14, decimal_places=3)
    previous_value = models.DecimalField(max_digits=14, decimal_places=3, null=True, blank=True)
    rate = models.DecimalField(max_digits=10, decimal_places=5, default=0)
    charge = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    is_correction = models.BooleanField(default=False)
    notes = models.TextField(blank=True)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    reading_kind = models.CharField(max_length=12, choices=Kind.choices, default=Kind.READING)
    reading_date = models.DateField(default=timezone.localdate)
    period_start = models.DateField(null=True, blank=True)
    period_end = models.DateField(null=True, blank=True)
    previous_reading_record = models.ForeignKey("self", on_delete=models.PROTECT, null=True, blank=True, related_name="dependent_readings")
    current_reading = models.DecimalField(max_digits=14, decimal_places=3, default=0)
    consumption = models.DecimalField(max_digits=14, decimal_places=3, default=0)
    adjustment_consumption = models.DecimalField(max_digits=14, decimal_places=3, default=0)
    currency = models.CharField(max_length=3, default="OMR")
    reference = models.CharField(max_length=80, blank=True)
    corrects_reading = models.ForeignKey("self", on_delete=models.PROTECT, null=True, blank=True, related_name="corrections")
    invoice_line_item = models.OneToOneField("billing.InvoiceLineItem", on_delete=models.PROTECT, null=True, blank=True, related_name="utility_reading")
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("meter", "read_at"), name="unique_meter_read_time"), models.UniqueConstraint(fields=("meter", "reading_date", "reading_kind"), condition=models.Q(reading_kind="reading"), name="unique_meter_reading_date")]
        ordering = ("-reading_date", "-id")

    def clean(self):
        self.currency = self.currency.upper()
        if self.period_start and self.period_end and self.period_end < self.period_start:
            raise ValidationError({"period_end": _("Period end cannot be before period start.")})
        if self.reading_kind == self.Kind.READING and self.previous_value is not None and self.current_reading < self.previous_value:
            raise ValidationError({"current_reading": _("Current reading cannot be lower than the previous reading.")})


class InspectionTemplate(models.Model):
    class Type(models.TextChoices):
        MOVE_IN = "move_in", _("Move in")
        MOVE_OUT = "move_out", _("Move out")
        PERIODIC = "periodic", _("Periodic")

    name = models.CharField(max_length=160, unique=True)
    description = models.TextField(blank=True)
    inspection_type = models.CharField(max_length=12, choices=Type.choices, default=Type.PERIODIC)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class InspectionTemplateItem(models.Model):
    template = models.ForeignKey(InspectionTemplate, on_delete=models.CASCADE, related_name="items")
    label = models.CharField(max_length=200)
    guidance = models.TextField(blank=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("sort_order", "id")


class Inspection(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        COMPLETED = "completed", _("Completed")
        CANCELLED = "cancelled", _("Cancelled")

    template = models.ForeignKey(InspectionTemplate, on_delete=models.PROTECT)
    template_name = models.CharField(max_length=160, blank=True)
    property = models.ForeignKey("properties.Property", on_delete=models.PROTECT, null=True, blank=True, related_name="inspections")
    unit = models.ForeignKey("properties.Unit", on_delete=models.PROTECT, null=True, blank=True, related_name="inspections")
    lease = models.ForeignKey("properties.Lease", on_delete=models.SET_NULL, null=True, blank=True, related_name="inspections")
    inspection_type = models.CharField(max_length=12, choices=InspectionTemplate.Type.choices, default=InspectionTemplate.Type.PERIODIC)
    inspection_date = models.DateField(default=timezone.localdate)
    inspector = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="inspections")
    scheduled_for = models.DateTimeField()
    completed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="completed_inspections")
    completed_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=14, choices=Status.choices, default=Status.DRAFT)
    notes = models.TextField(blank=True)
    damage_observations = models.TextField(blank=True)

    class Meta:
        ordering = ("-scheduled_for",)

    def __str__(self):
        return f"{self.property or self.unit} · {self.inspection_date:%Y-%m-%d}"


class InspectionItem(models.Model):
    class Condition(models.TextChoices):
        GOOD = "good", _("Good")
        FAIR = "fair", _("Fair")
        POOR = "poor", _("Poor")
        NOT_APPLICABLE = "na", _("Not applicable")

    inspection = models.ForeignKey(Inspection, on_delete=models.CASCADE, related_name="items")
    label = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    condition = models.CharField(max_length=8, choices=Condition.choices, blank=True)
    notes = models.TextField(blank=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("sort_order", "id")


class InspectionPhoto(models.Model):
    item = models.ForeignKey(InspectionItem, on_delete=models.CASCADE, related_name="photos")
    file = models.ImageField(upload_to="inspections/%Y/%m", validators=[FileExtensionValidator(("jpg", "jpeg", "png", "webp"))])
    original_name = models.CharField(max_length=255, blank=True)
    mime_type = models.CharField(max_length=120, blank=True)
    size = models.PositiveBigIntegerField(default=0)
    caption = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class ReminderLog(models.Model):
    kind = models.CharField(max_length=80)
    recipient = models.CharField(max_length=255)
    channel = models.CharField(max_length=30)
    subject_type = models.CharField(max_length=100, blank=True)
    subject_id = models.CharField(max_length=80, blank=True)
    status = models.CharField(max_length=30, default="queued")
    reminder_date = models.DateField(default=timezone.localdate)
    overdue_days = models.IntegerField(default=-1)
    dedupe_key = models.CharField(max_length=255, unique=True, null=True, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    error_message = models.TextField(blank=True)
    provider_reference = models.CharField(max_length=160, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)


class ReminderSettings(models.Model):
    enabled = models.BooleanField(default=True)
    days_before = models.PositiveSmallIntegerField(default=3)
    overdue_intervals = models.JSONField(default=list, blank=True)
    channels = models.JSONField(default=list, blank=True)
    lease_expiration_days = models.PositiveSmallIntegerField(default=30)
    upcoming_template = models.TextField(default="Rent for invoice {invoice} is due on {due_date}. Balance: {currency} {balance}.")
    due_template = models.TextField(default="Rent for invoice {invoice} is due today. Balance: {currency} {balance}.")
    overdue_template = models.TextField(default="Invoice {invoice} is {overdue_days} day(s) overdue. Balance: {currency} {balance}.")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "reminder settings"

    def clean(self):
        intervals = self.overdue_intervals or []
        if any(not isinstance(value, int) or value < 1 for value in intervals):
            raise ValidationError({"overdue_intervals": _("Use positive whole-day intervals.")})
        allowed = {"database", "email", "whatsapp", "log"}
        if not set(self.channels or []).issubset(allowed):
            raise ValidationError({"channels": _("An unsupported reminder channel was selected.")})

    @classmethod
    def load(cls):
        obj, _created = cls.objects.get_or_create(pk=1, defaults={"overdue_intervals": [1, 3, 7], "channels": ["database", "log"]})
        return obj


class UserNotification(models.Model):
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="pms_notifications")
    kind = models.CharField(max_length=80)
    title = models.CharField(max_length=200)
    message = models.TextField()
    url = models.CharField(max_length=500, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at", "-id")
        indexes = [models.Index(fields=("recipient", "read_at"))]

    def mark_read(self):
        if self.read_at is None:
            self.read_at = timezone.now()
            self.save(update_fields=("read_at",))
