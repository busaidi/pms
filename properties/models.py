import builtins
import hashlib
import secrets
from django.conf import settings
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.db import models
from django.utils import timezone
from django.utils.text import slugify
from PIL import Image, UnidentifiedImageError
from django.utils.translation import gettext_lazy as _
from .contract_storage import contract_storage


class Region(models.Model):
    name = models.CharField(max_length=100)
    country_code = models.CharField(max_length=2, default="OM")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("country_code", "name")
        constraints = [models.UniqueConstraint(fields=("country_code", "name"), name="unique_region_country_name")]

    def __str__(self):
        return f"{self.name}, {self.country_code}"


class City(models.Model):
    region = models.ForeignKey(Region, on_delete=models.PROTECT, related_name="cities")
    name = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("region__name", "name")
        constraints = [models.UniqueConstraint(fields=("region", "name"), name="unique_city_region_name")]

    def __str__(self):
        return self.name


class PropertyType(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True, null=True, blank=True)
    description = models.TextField(blank=True)
    default_rental_mode = models.CharField(max_length=20, choices=(("unit", "Individual units"), ("whole_property", "Whole property"), ("hybrid", "Both")), default="unit")
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("sort_order", "name")

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Amenity(models.Model):
    name = models.CharField(max_length=100, unique=True)
    icon = models.CharField(max_length=60, blank=True)

    class Meta:
        verbose_name_plural = "amenities"
        ordering = ("name",)

    def __str__(self):
        return self.name


class Property(models.Model):
    class RentalMode(models.TextChoices):
        UNIT = "unit", _("By unit")
        WHOLE = "whole_property", _("Whole property")
        HYBRID = "hybrid", _("Hybrid")

    name = models.CharField(max_length=160)
    slug = models.SlugField(max_length=180, unique=True, null=True, blank=True)
    property_type = models.ForeignKey(PropertyType, on_delete=models.PROTECT, null=True, blank=True)
    address = models.TextField()
    city = models.CharField(max_length=100, default="Muscat")
    region = models.CharField(max_length=100, blank=True)
    city_ref = models.ForeignKey(City, on_delete=models.PROTECT, null=True, blank=True, related_name="properties")
    region_ref = models.ForeignKey(Region, on_delete=models.PROTECT, null=True, blank=True, related_name="properties")
    postal_code = models.CharField(max_length=20, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    description = models.TextField(blank=True)
    rental_mode = models.CharField(max_length=20, choices=RentalMode.choices, default=RentalMode.UNIT)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    amenities = models.ManyToManyField(Amenity, blank=True, related_name="properties")
    is_public = models.BooleanField(default=False)
    public_slug = models.SlugField(max_length=180, unique=True, null=True, blank=True)
    is_published = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    archived_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "properties"
        ordering = ("name",)

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name) or "property"
            candidate, suffix = base, 2
            while Property.objects.exclude(pk=self.pk).filter(slug=candidate).exists():
                candidate, suffix = f"{base}-{suffix}", suffix + 1
            self.slug = candidate
        if self.rental_mode == "whole":
            self.rental_mode = self.RentalMode.WHOLE
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        if self.city_ref_id and self.region_ref_id and self.city_ref.region_id != self.region_ref_id:
            raise ValidationError({"city_ref": _("Choose a city within the selected region.")})
        if self.pk:
            previous_mode = Property.objects.filter(pk=self.pk).values_list("rental_mode", flat=True).first()
            if previous_mode and previous_mode != self.rental_mode:
                if self.is_published:
                    raise ValidationError({"rental_mode": _("Unpublish the property before changing its rental model.")})
                if self.rental_mode == self.RentalMode.WHOLE and Lease.objects.filter(unit__property=self, status__in=("active", "pending", "notice")).exists():
                    raise ValidationError({"rental_mode": _("A property with current unit leases cannot change to whole-property rental.")})
                if self.rental_mode == self.RentalMode.UNIT and Lease.objects.filter(property=self, unit__isnull=True, status="active").exists():
                    raise ValidationError({"rental_mode": _("A property with a current whole-property lease cannot change to unit rental.")})

    @property
    def supports_unit_inventory(self):
        return self.rental_mode != self.RentalMode.WHOLE

    @property
    def supports_property_pricing(self):
        return self.rental_mode != self.RentalMode.UNIT

    def archive(self):
        if Lease.objects.filter(property=self, status__in=("active", "pending", "notice")).exists():
            raise ValidationError(_("A property with current leases cannot be archived."))
        self.archived_at = timezone.now()
        self.is_active = False
        self.is_published = False
        self.is_public = False
        self.save(update_fields=("archived_at", "is_active", "is_published", "is_public", "updated_at"))

    def restore(self):
        self.archived_at = None
        self.is_active = True
        self.save(update_fields=("archived_at", "is_active", "updated_at"))


class Unit(models.Model):
    class Status(models.TextChoices):
        AVAILABLE = "available", _("Available")
        OCCUPIED = "occupied", _("Occupied")
        MAINTENANCE = "maintenance", _("Maintenance")
        UNAVAILABLE = "unavailable", _("Unavailable")

    class Furnishing(models.TextChoices):
        UNFURNISHED = "unfurnished", _("Unfurnished")
        SEMI = "semi_furnished", _("Semi furnished")
        FURNISHED = "furnished", _("Furnished")

    property = models.ForeignKey(
        Property, on_delete=models.CASCADE, related_name="units"
    )
    unit_type = models.ForeignKey("UnitType", on_delete=models.PROTECT, null=True, blank=True, related_name="units")
    name = models.CharField(max_length=80)
    slug = models.SlugField(max_length=100, null=True, blank=True)
    monthly_rent = models.DecimalField(max_digits=10, decimal_places=3)
    bedrooms = models.PositiveSmallIntegerField(default=1)
    bathrooms = models.DecimalField(max_digits=3, decimal_places=1, default=1)
    area_sqm = models.DecimalField(max_digits=9, decimal_places=2, null=True, blank=True)
    floor = models.CharField(max_length=30, blank=True)
    is_furnished = models.BooleanField(default=False)
    furnishing = models.CharField(max_length=20, choices=Furnishing.choices, default=Furnishing.UNFURNISHED)
    capacity = models.PositiveSmallIntegerField(default=1)
    notes = models.TextField(blank=True)
    description = models.TextField(blank=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.AVAILABLE
    )
    archived_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("property__name", "name")
        constraints = [
            models.UniqueConstraint(
                fields=("property", "name"), name="unique_unit_per_property"
            ),
            models.UniqueConstraint(fields=("property", "slug"), name="unique_unit_slug_per_property"),
        ]

    def __str__(self):
        return f"{self.property} — {self.name}"

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name) or "unit"
            candidate, suffix = base, 2
            while Unit.objects.exclude(pk=self.pk).filter(property=self.property, slug=candidate).exists():
                candidate, suffix = f"{base}-{suffix}", suffix + 1
            self.slug = candidate
        self.is_furnished = self.furnishing == self.Furnishing.FURNISHED
        super().save(*args, **kwargs)

    @builtins.property
    def is_available_for_assignment(self):
        return self.archived_at is None and self.status not in (self.Status.MAINTENANCE, self.Status.UNAVAILABLE)


class UnitType(models.Model):
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="unit_types")
    name = models.CharField(max_length=100)
    public_slug = models.SlugField(max_length=120, null=True, blank=True)
    description = models.TextField(blank=True)
    bedrooms = models.PositiveSmallIntegerField(default=1)
    bathrooms = models.DecimalField(max_digits=3, decimal_places=1, default=1)
    area_sqm = models.DecimalField(max_digits=9, decimal_places=2, null=True, blank=True)
    furnishing = models.CharField(max_length=20, choices=Unit.Furnishing.choices, default=Unit.Furnishing.UNFURNISHED)
    is_active = models.BooleanField(default=True)
    is_published = models.BooleanField(default=False)
    archived_at = models.DateTimeField(null=True, blank=True)
    amenities = models.ManyToManyField(Amenity, blank=True, related_name="unit_types")

    class Meta:
        constraints = [models.UniqueConstraint(fields=("property", "name"), name="unique_unit_type_per_property"), models.UniqueConstraint(fields=("property", "public_slug"), name="unique_unit_type_slug_per_property")]
        ordering = ("property__name", "name")

    def __str__(self):
        return f"{self.property} — {self.name}"

    def save(self, *args, **kwargs):
        if not self.public_slug:
            self.public_slug = slugify(self.name) or "unit-type"
        super().save(*args, **kwargs)


class RateMixin(models.Model):
    class BillingUnit(models.TextChoices):
        DAY = "day", _("Day")
        WEEK = "week", _("Week")
        MONTH = "month", _("Month")
        YEAR = "year", _("Year")

    name = models.CharField(max_length=100, default="Standard")
    amount = models.DecimalField(max_digits=12, decimal_places=3)
    currency = models.CharField(max_length=3, default="OMR")
    billing_interval = models.PositiveSmallIntegerField(default=1)
    billing_unit = models.CharField(max_length=10, choices=BillingUnit.choices, default=BillingUnit.MONTH)
    is_active = models.BooleanField(default=True)
    starts_on = models.DateField(default=timezone.localdate)
    ends_on = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True

    def clean(self):
        if self.ends_on and self.ends_on < self.starts_on:
            raise ValidationError({"ends_on": _("End date must be on or after start date.")})
        self.currency = self.currency.upper()
        if len(self.currency) != 3 or not self.currency.isalpha():
            raise ValidationError({"currency": _("Use a three-letter ISO currency code.")})
        if self.billing_interval < 1:
            raise ValidationError({"billing_interval": _("Billing interval must be at least 1.")})

    def is_effective(self, on_date=None):
        on_date = on_date or timezone.localdate()
        return self.is_active and self.starts_on <= on_date and (self.ends_on is None or self.ends_on >= on_date)


class PropertyRate(RateMixin):
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="rates")

    class Meta:
        ordering = ("billing_unit", "billing_interval", "currency")
        constraints = [models.UniqueConstraint(fields=("property", "billing_interval", "billing_unit", "currency", "starts_on"), name="unique_property_rate_period")]

    def __str__(self):
        return f"{self.property} · {self.name}"


class UnitTypeRate(RateMixin):
    unit_type = models.ForeignKey(UnitType, on_delete=models.CASCADE, related_name="rates")

    class Meta:
        ordering = ("billing_unit", "billing_interval", "currency")
        constraints = [models.UniqueConstraint(fields=("unit_type", "billing_interval", "billing_unit", "currency", "starts_on"), name="unique_unit_type_rate_period")]

    def __str__(self):
        return f"{self.unit_type} · {self.name}"


class UnitRate(RateMixin):
    unit = models.ForeignKey(Unit, on_delete=models.CASCADE, related_name="rates")

    class Meta:
        ordering = ("billing_unit", "billing_interval", "currency")
        constraints = [models.UniqueConstraint(fields=("unit", "billing_interval", "billing_unit", "currency", "starts_on"), name="unique_unit_rate_period")]

    def __str__(self):
        return f"{self.unit} · {self.name}"


class PropertyMedia(models.Model):
    class Kind(models.TextChoices):
        IMAGE = "image", _("Image")
        DOCUMENT = "document", _("Document")
        FLOORPLAN = "floorplan", _("Floor plan")

    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="media")
    unit_type = models.ForeignKey(UnitType, on_delete=models.CASCADE, null=True, blank=True, related_name="media")
    file = models.FileField(upload_to="properties/%Y/%m", validators=[FileExtensionValidator(("jpg", "jpeg", "png", "webp", "gif", "pdf", "doc", "docx"))])
    kind = models.CharField(max_length=12, choices=Kind.choices, default=Kind.IMAGE)
    caption = models.CharField(max_length=200, blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    is_public = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("sort_order", "id")

    def __str__(self):
        return self.caption or self.file.name

    def clean(self):
        super().clean()
        extension = self.file.name.rsplit(".", 1)[-1].lower() if self.file else ""
        if self.kind in (self.Kind.IMAGE, self.Kind.FLOORPLAN) and extension not in {"jpg", "jpeg", "png", "webp", "gif"}:
            raise ValidationError({"file": _("Gallery items must use JPG, PNG, WebP, or GIF.")})
        if self.kind in (self.Kind.IMAGE, self.Kind.FLOORPLAN) and self.file:
            try:
                self.file.open("rb")
                Image.open(self.file).verify()
                self.file.seek(0)
            except (UnidentifiedImageError, OSError, ValueError):
                raise ValidationError({"file": _("The uploaded file is not a valid image.")})
        if self.file and self.file.size > 10 * 1024 * 1024:
            raise ValidationError({"file": _("Files may not exceed 10 MB.")})


class Tenant(models.Model):
    user = models.OneToOneField("auth.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="tenant_profile")
    created_by = models.ForeignKey("auth.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="created_tenants")
    full_name = models.CharField(max_length=160)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=30)
    id_number = models.CharField(max_length=80, blank=True, default="")
    nationality = models.CharField(max_length=80, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    emergency_contact = models.CharField(max_length=160, blank=True)
    emergency_contact_name = models.CharField(max_length=160, blank=True)
    emergency_contact_phone = models.CharField(max_length=30, blank=True)
    notes = models.TextField(blank=True)
    portal_enabled = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    archived_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("full_name",)
        constraints = [
            models.UniqueConstraint(
                fields=("id_number",),
                condition=~models.Q(id_number=""),
                name="unique_nonempty_tenant_id",
            )
        ]

    def __str__(self):
        return self.full_name

    def archive(self):
        if self.leases.filter(status=Lease.Status.ACTIVE).exists() or self.shared_leases.filter(status=Lease.Status.ACTIVE).exists():
            raise ValidationError(_("A tenant with an active lease cannot be archived."))
        self.archived_at = timezone.now(); self.is_active = False
        self.save(update_fields=("archived_at", "is_active", "updated_at"))

    def restore(self):
        self.archived_at = None; self.is_active = True
        self.save(update_fields=("archived_at", "is_active", "updated_at"))


class Lease(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        ACTIVE = "active", _("Active")
        PENDING = "pending", _("Pending")
        NOTICE = "notice", _("Notice given")
        EXPIRED = "expired", _("Expired")
        ENDED = "ended", _("Ended")
        TERMINATED = "terminated", _("Terminated")
        RENEWED = "renewed", _("Renewed")

    class BillingStrategy(models.TextChoices):
        ADVANCE = "advance", _("Advance")
        ARREARS = "arrears", _("Arrears")

    reference = models.CharField(max_length=32, unique=True, null=True, blank=True)
    property = models.ForeignKey(Property, on_delete=models.PROTECT, null=True, blank=True, related_name="leases")
    primary_tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, null=True, blank=True, related_name="primary_leases")

    unit = models.ForeignKey(Unit, on_delete=models.PROTECT, null=True, blank=True, related_name="leases")
    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="leases")
    tenants = models.ManyToManyField(Tenant, blank=True, related_name="shared_leases")
    start_date = models.DateField()
    end_date = models.DateField(blank=True, null=True)
    monthly_rent = models.DecimalField(max_digits=10, decimal_places=3)
    rent_amount = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    currency = models.CharField(max_length=3, default="OMR")
    billing_interval = models.PositiveSmallIntegerField(default=1)
    billing_unit = models.CharField(max_length=10, choices=RateMixin.BillingUnit.choices, default=RateMixin.BillingUnit.MONTH)
    billing_strategy = models.CharField(max_length=10, choices=BillingStrategy.choices, default=BillingStrategy.ADVANCE)
    is_custom_price = models.BooleanField(default=False)
    unit_rate = models.ForeignKey(UnitRate, on_delete=models.SET_NULL, null=True, blank=True, related_name="leases")
    unit_type_rate = models.ForeignKey(UnitTypeRate, on_delete=models.SET_NULL, null=True, blank=True, related_name="leases")
    property_rate = models.ForeignKey(PropertyRate, on_delete=models.SET_NULL, null=True, blank=True, related_name="leases")
    security_deposit = models.DecimalField(max_digits=10, decimal_places=3, default=0)
    deposit_paid_at = models.DateTimeField(null=True, blank=True)
    deposit_refund_amount = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    deposit_refunded_at = models.DateTimeField(null=True, blank=True)
    billing_day = models.PositiveSmallIntegerField(default=1)
    notice_date = models.DateField(null=True, blank=True)
    move_out_date = models.DateField(null=True, blank=True)
    handover_confirmed_at = models.DateTimeField(null=True, blank=True)
    handover_confirmed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="confirmed_lease_handovers")
    terms = models.TextField(blank=True)
    terms_template = models.ForeignKey("ContractTermsTemplate", on_delete=models.PROTECT, null=True, blank=True, related_name="leases")
    notes = models.TextField(blank=True)
    termination_date = models.DateField(null=True, blank=True)
    termination_reason = models.TextField(blank=True)
    previous_lease = models.OneToOneField("self", on_delete=models.PROTECT, null=True, blank=True, related_name="renewed_lease")
    archived_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.DRAFT
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-start_date",)

    def __str__(self):
        return self.reference or f"{self.tenant} — {self.unit or self.property}"

    def clean(self):
        if self.end_date and self.end_date < self.start_date:
            raise ValidationError({"end_date": _("End date must be on or after start date.")})
        if self.terms_template_id and self.property_id and self.terms_template.property_id != self.property_id:
            raise ValidationError({"terms_template": "قالب الشروط لا يتبع العقار المحدد."})
        if not 1 <= self.billing_day <= 28:
            raise ValidationError({"billing_day": _("Billing day must be between 1 and 28.")})
        if self.property_id and self.unit_id and self.unit.property_id != self.property_id:
            raise ValidationError({"unit": _("The unit does not belong to the selected property.")})
        if self.unit_id is None and self.property_rate_id is None:
            raise ValidationError({"property_rate": _("Whole-property leases require a property rate.")})
        if self.unit_id and self.property_rate_id:
            raise ValidationError({"property_rate": _("Unit leases cannot use a property rate.")})

    def save(self, *args, **kwargs):
        if self.unit_id and not self.property_id:
            self.property_id = self.unit.property_id
        if not self.primary_tenant_id:
            self.primary_tenant_id = self.tenant_id
        if self.rent_amount is None:
            self.rent_amount = self.monthly_rent
        self.monthly_rent = self.rent_amount
        self.currency = self.currency.upper()
        if not self.reference:
            year = timezone.localdate().year
            prefix = f"LSX{year}"
            last = Lease.objects.filter(reference__startswith=prefix).order_by("-reference").values_list("reference", flat=True).first()
            number = int(last[len(prefix):]) + 1 if last else 1
            self.reference = f"{prefix}{number:04d}"
        super().save(*args, **kwargs)

    @builtins.property
    def target_type(self):
        return "unit" if self.unit_id else "whole_property"

    @builtins.property
    def awaiting_action(self):
        # Expiry does not end occupancy or release the unit.
        return self.status == self.Status.ACTIVE and bool(self.end_date and self.end_date < timezone.localdate())

    @builtins.property
    def lifecycle_label(self):
        return "انتهت المدة — بانتظار الإجراء" if self.awaiting_action else self.get_status_display()

    @builtins.property
    def outstanding_balance(self):
        return sum((invoice.balance for invoice in self.invoices.exclude(status__in=("paid", "void"))), Decimal("0"))


class ContractTermsTemplate(models.Model):
    property = models.ForeignKey(Property, on_delete=models.PROTECT, related_name="terms_templates")
    name = models.CharField(max_length=160)
    body = models.TextField()
    is_active = models.BooleanField(default=True)
    is_default = models.BooleanField(default=False)
    revision = models.PositiveIntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("property__name", "name")
        constraints = [models.UniqueConstraint(fields=("property",), condition=models.Q(is_default=True), name="one_default_terms_per_property")]

    def __str__(self):
        return f"{self.property.name} — {self.name}"


class LeaseContractProfile(models.Model):
    property = models.OneToOneField(Property, on_delete=models.CASCADE, related_name="contract_profile")
    display_name = models.CharField(max_length=160, blank=True)
    location = models.CharField(max_length=255, blank=True)
    lessor_name = models.CharField(max_length=160, blank=True)
    lessor_phone = models.CharField(max_length=30, blank=True)
    lessor_email = models.EmailField(blank=True)
    lessor_signature = models.FileField(upload_to="signatures", storage=contract_storage, blank=True)
    plot_number = models.CharField(max_length=40, blank=True)
    building_number = models.CharField(max_length=40, blank=True)
    block_number = models.CharField(max_length=40, blank=True)
    road_number = models.CharField(max_length=40, blank=True)


class LeaseContract(models.Model):
    """A versioned snapshot; later lease edits never rewrite an issued version."""

    lease = models.ForeignKey(Lease, on_delete=models.PROTECT, related_name="contracts")
    revision = models.PositiveIntegerField()
    template_version = models.CharField(max_length=40, default="atheer-short-v2")
    fingerprint = models.CharField(max_length=64)
    snapshot = models.JSONField()
    file = models.FileField(upload_to="%Y/%m", storage=contract_storage, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-revision",)
        constraints = [models.UniqueConstraint(fields=("lease", "revision"), name="unique_lease_contract_revision")]


class TenantDocument(models.Model):
    class Type(models.TextChoices):
        ID_CARD = "id_card", _("ID card")
        PASSPORT = "passport", _("Passport")
        LEASE = "lease", _("Lease/agreement")
        SUPPORTING = "supporting", _("Supporting")
        OTHER = "other", _("Other")
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="documents")
    name = models.CharField(max_length=160)
    file = models.FileField(upload_to="tenants/%Y/%m")
    document_type = models.CharField(max_length=16, choices=Type.choices, default=Type.OTHER)
    mime_type = models.CharField(max_length=120, blank=True)
    size = models.PositiveBigIntegerField(default=0)
    expires_on = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.tenant} · {self.name}"


class RentSchedule(models.Model):
    class Status(models.TextChoices):
        SCHEDULED = "scheduled", _("Scheduled")
        INVOICED = "invoiced", _("Invoiced")
        PAID = "paid", _("Paid")
        WAIVED = "waived", _("Waived")

    lease = models.ForeignKey(Lease, on_delete=models.CASCADE, related_name="rent_schedule")
    due_date = models.DateField()
    period_start = models.DateField(null=True, blank=True)
    period_end = models.DateField(null=True, blank=True)
    amount = models.DecimalField(max_digits=10, decimal_places=3)
    currency = models.CharField(max_length=3, default="OMR")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.SCHEDULED)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("lease", "due_date"), name="unique_lease_rent_due_date")]
        ordering = ("due_date",)

    def __str__(self):
        return f"{self.lease} · {self.due_date}"


class LeaseUnitHistory(models.Model):
    lease = models.ForeignKey(Lease, on_delete=models.CASCADE, related_name="unit_history")
    unit = models.ForeignKey(Unit, on_delete=models.PROTECT)
    moved_in_at = models.DateField()
    moved_out_at = models.DateField(null=True, blank=True)
    reason = models.CharField(max_length=200, blank=True)
    from_unit = models.ForeignKey(Unit, on_delete=models.PROTECT, null=True, blank=True, related_name="moves_from")
    to_unit = models.ForeignKey(Unit, on_delete=models.PROTECT, null=True, blank=True, related_name="moves_to")
    effective_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    transferred_by = models.ForeignKey("auth.User", on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        ordering = ("-moved_in_at",)


class DepositSettlement(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        SETTLED = "settled", _("Settled")
    lease = models.OneToOneField(Lease, on_delete=models.CASCADE, related_name="deposit_settlement")
    deposit_received = models.DecimalField(max_digits=10, decimal_places=3, default=0)
    refund_amount = models.DecimalField(max_digits=10, decimal_places=3, default=0)
    original_amount = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    currency = models.CharField(max_length=3, default="OMR")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    settlement_date = models.DateField(null=True, blank=True)
    refund_reference = models.CharField(max_length=120, blank=True)
    settled_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)


class DepositDeduction(models.Model):
    settlement = models.ForeignKey(DepositSettlement, on_delete=models.CASCADE, related_name="deductions")
    description = models.CharField(max_length=200)
    amount = models.DecimalField(max_digits=10, decimal_places=3)


class TenantInvitation(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="invitations")
    email = models.EmailField()
    token_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    @builtins.property
    def is_usable(self):
        return self.accepted_at is None and self.expires_at > timezone.now()

    @classmethod
    def issue(cls, tenant, email):
        cls.objects.filter(tenant=tenant, accepted_at__isnull=True).update(expires_at=timezone.now())
        raw = secrets.token_urlsafe(32)
        obj = cls.objects.create(tenant=tenant, email=email, token_hash=hashlib.sha256(raw.encode()).hexdigest(), expires_at=timezone.now() + timedelta(days=3))
        return obj, raw


class LeaseNotificationEvent(models.Model):
    lease = models.ForeignKey(Lease, on_delete=models.CASCADE, related_name="notification_events")
    kind = models.CharField(max_length=40, default="expiration")
    scheduled_for = models.DateField()
    status = models.CharField(max_length=12, choices=(("pending", "Pending"), ("sent", "Sent"), ("failed", "Failed")), default="pending")
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("lease", "kind", "scheduled_for"), name="unique_lease_notification_event")]

# Create your models here.
