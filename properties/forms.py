from django import forms
from core.forms import LocalizedFormMixin

from .models import Amenity, ContractTermsTemplate, Lease, Property, PropertyMedia, PropertyRate, PropertyType, Tenant, TenantDocument, Unit, UnitRate, UnitType, UnitTypeRate
from django.utils.translation import gettext_lazy as _


class StyledModelForm(LocalizedFormMixin, forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")


class PropertyForm(StyledModelForm):
    class Meta:
        model = Property
        fields = ("name", "slug", "property_type", "rental_mode", "region_ref", "city_ref", "address", "postal_code", "phone", "description", "latitude", "longitude", "amenities", "is_active", "public_slug")
        widgets = {"description": forms.Textarea(attrs={"rows": 4}), "address": forms.Textarea(attrs={"rows": 2}), "amenities": forms.CheckboxSelectMultiple}


class PropertyTypeForm(StyledModelForm):
    class Meta:
        model = PropertyType
        fields = ("name", "slug", "description", "default_rental_mode", "sort_order", "is_active")


class AmenityForm(StyledModelForm):
    class Meta:
        model = Amenity
        fields = ("name", "icon")


class UnitTypeForm(StyledModelForm):
    class Meta:
        model = UnitType
        fields = ("name", "public_slug", "description", "bedrooms", "bathrooms", "area_sqm", "furnishing", "amenities", "is_active", "is_published")
        widgets = {"amenities": forms.CheckboxSelectMultiple, "description": forms.Textarea(attrs={"rows": 3})}


class UnitForm(StyledModelForm):
    class Meta:
        model = Unit
        fields = ("name", "slug", "unit_type", "monthly_rent", "bedrooms", "bathrooms", "area_sqm", "floor", "capacity", "furnishing", "status", "description", "notes")

    def __init__(self, *args, property_obj=None, **kwargs):
        super().__init__(*args, **kwargs)
        if property_obj:
            self.fields["unit_type"].queryset = property_obj.unit_types.filter(archived_at__isnull=True)


class RateForm(StyledModelForm):
    class Meta:
        fields = ("name", "amount", "currency", "billing_interval", "billing_unit", "is_active", "starts_on", "ends_on")
        widgets = {"starts_on": forms.DateInput(attrs={"type": "date"}), "ends_on": forms.DateInput(attrs={"type": "date"})}


class PropertyRateForm(RateForm):
    class Meta(RateForm.Meta):
        model = PropertyRate


class UnitTypeRateForm(RateForm):
    class Meta(RateForm.Meta):
        model = UnitTypeRate


class UnitRateForm(RateForm):
    class Meta(RateForm.Meta):
        model = UnitRate


class MediaForm(StyledModelForm):
    class Meta:
        model = PropertyMedia
        fields = ("unit_type", "file", "kind", "caption", "sort_order", "is_public")

    def __init__(self, *args, property_obj=None, **kwargs):
        super().__init__(*args, **kwargs)
        if property_obj:
            self.fields["unit_type"].queryset = property_obj.unit_types.filter(archived_at__isnull=True)


class TenantForm(StyledModelForm):
    class Meta:
        model = Tenant
        fields = ("full_name", "email", "phone", "id_number", "nationality", "date_of_birth", "emergency_contact_name", "emergency_contact_phone", "notes", "is_active")
        widgets = {"date_of_birth": forms.DateInput(attrs={"type": "date"}), "notes": forms.Textarea(attrs={"rows": 3})}


class TenantIdentityForm(forms.Form):
    id_card_file = forms.FileField(required=False, label="البطاقة الشخصية", widget=forms.ClearableFileInput(attrs={"accept": ".pdf,.jpg,.jpeg,.png", "class": "form-control"}))
    passport_file = forms.FileField(required=False, label="جواز السفر", widget=forms.ClearableFileInput(attrs={"accept": ".pdf,.jpg,.jpeg,.png", "class": "form-control"}))

    def clean(self):
        cleaned = super().clean()
        for name in ("id_card_file", "passport_file"):
            uploaded = cleaned.get(name)
            if not uploaded:
                continue
            extension = uploaded.name.rsplit(".", 1)[-1].lower()
            if extension not in {"pdf", "jpg", "jpeg", "png"}:
                self.add_error(name, "ارفق ملف PDF أو صورة JPG أو PNG.")
            elif uploaded.size > 10 * 1024 * 1024:
                self.add_error(name, "حجم الملف يجب ألا يتجاوز 10 ميجابايت.")
        return cleaned

    def save_documents(self, tenant):
        documents = []
        try:
            for field, kind, label in (("id_card_file", "id_card", "البطاقة الشخصية"), ("passport_file", "passport", "جواز السفر")):
                uploaded = self.cleaned_data.get(field)
                if uploaded:
                    document = TenantDocument(tenant=tenant, name=label, document_type=kind,
                                              file=uploaded, size=uploaded.size, mime_type=uploaded.content_type or "application/octet-stream")
                    documents.append(document)
                    document.save()
        except Exception:
            for document in documents:
                if document.file and document.file._committed:
                    document.file.storage.delete(document.file.name)
            raise
        return documents


class TenantDocumentForm(StyledModelForm):
    class Meta:
        model = TenantDocument
        fields = ("name", "document_type", "file", "expires_on")
        widgets = {"expires_on": forms.DateInput(attrs={"type": "date"})}

    def clean_file(self):
        uploaded = self.cleaned_data["file"]
        extension = uploaded.name.rsplit(".", 1)[-1].lower() if "." in uploaded.name else ""
        if extension not in {"pdf", "jpg", "jpeg", "png", "doc", "docx"}:
            raise forms.ValidationError(_("Upload a PDF, image, or Word document."))
        if uploaded.size > 10 * 1024 * 1024:
            raise forms.ValidationError(_("The document cannot exceed 10 MB."))
        return uploaded


class LeaseCreateForm(LocalizedFormMixin, forms.Form):
    terms_template = forms.ModelChoiceField(ContractTermsTemplate.objects.none(), required=False, label="قالب الشروط والأحكام", empty_label="شروط الإقامة المعتمدة للعقار")
    TARGETS = (("unit", "Specific unit"), ("unit_type", "Next available unit of a type"), ("whole_property", "Whole property"))
    property = forms.ModelChoiceField(Property.objects.none())
    target_type = forms.ChoiceField(choices=TARGETS)
    unit = forms.ModelChoiceField(Unit.objects.none(), required=False)
    unit_type = forms.ModelChoiceField(UnitType.objects.none(), required=False)
    tenants = forms.ModelMultipleChoiceField(Tenant.objects.filter(archived_at__isnull=True, is_active=True))
    start_date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    end_date = forms.DateField(required=False, label=_("Last rental day"), help_text=_("The departure date on the contract is the following day."), widget=forms.DateInput(attrs={"type": "date"}))
    rent_amount = forms.DecimalField(max_digits=12, decimal_places=3, required=False)
    currency = forms.CharField(max_length=3, required=False, initial="OMR")
    billing_interval = forms.IntegerField(min_value=1, required=False, initial=1)
    billing_unit = forms.ChoiceField(choices=PropertyRate.BillingUnit.choices, required=False)
    billing_strategy = forms.ChoiceField(choices=Lease.BillingStrategy.choices)
    billing_day = forms.IntegerField(min_value=1, max_value=28, initial=1)
    deposit_amount = forms.DecimalField(max_digits=12, decimal_places=3, initial=0)
    notes = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))

    def __init__(self, *args, properties=None, tenants=None, **kwargs):
        super().__init__(*args, **kwargs)
        properties = properties if properties is not None else Property.objects.none()
        self.fields["property"].queryset = properties.filter(archived_at__isnull=True, is_active=True)
        self.fields["terms_template"].queryset = ContractTermsTemplate.objects.filter(property__in=properties, is_active=True)
        self.fields["unit"].queryset = Unit.objects.filter(property__in=properties, archived_at__isnull=True)
        self.fields["unit_type"].queryset = UnitType.objects.filter(property__in=properties, archived_at__isnull=True, is_active=True)
        if tenants is not None: self.fields["tenants"].queryset = tenants.filter(archived_at__isnull=True, is_active=True)
        for field in self.fields.values(): field.widget.attrs.setdefault("class", "form-control")

    def clean(self):
        cleaned = super().clean(); target = cleaned.get("target_type"); property_obj = cleaned.get("property")
        if cleaned.get("terms_template") and property_obj and cleaned["terms_template"].property_id != property_obj.pk:
            self.add_error("terms_template", "القالب لا يتبع العقار المحدد.")
        if target == "unit" and not cleaned.get("unit"): self.add_error("unit", _("Select a unit."))
        if target == "unit_type" and not cleaned.get("unit_type"): self.add_error("unit_type", _("Select a unit type."))
        if cleaned.get("unit") and property_obj and cleaned["unit"].property_id != property_obj.pk: self.add_error("unit", _("Unit is outside the selected property."))
        if cleaned.get("unit_type") and property_obj and cleaned["unit_type"].property_id != property_obj.pk: self.add_error("unit_type", _("Unit type is outside the selected property."))
        return cleaned


class LeaseEditForm(StyledModelForm):
    class Meta:
        model = Lease
        fields = ("end_date", "rent_amount", "billing_strategy", "billing_day", "security_deposit", "deposit_paid_at", "notes")
        widgets = {"end_date": forms.DateInput(attrs={"type": "date"}), "deposit_paid_at": forms.DateTimeInput(attrs={"type": "datetime-local"}), "notes": forms.Textarea(attrs={"rows": 3})}

    def clean_end_date(self):
        end_date = self.cleaned_data.get("end_date")
        if end_date and self.instance.start_date and end_date < self.instance.start_date:
            raise forms.ValidationError(_("The end date cannot precede the lease start date."))
        return end_date
