from django import forms
from django.contrib.auth import get_user_model
from core.forms import LocalizedFormMixin

from properties.models import Property, Unit

from .models import Expense, ExpenseCategory, Inspection, InspectionTemplate, MaintenanceTicket, RecurringExpense, ReminderSettings, UtilityMeter
from django.utils.translation import gettext_lazy as _


class ExpenseForm(LocalizedFormMixin, forms.ModelForm):
    class Meta:
        model = Expense
        fields = ("property", "category", "amount", "currency", "incurred_on", "vendor", "reference", "description", "notes", "receipt")
        widgets = {"incurred_on": forms.DateInput(attrs={"type": "date"}), "description": forms.Textarea(attrs={"rows": 3}), "notes": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, properties=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["property"].queryset = (properties if properties is not None else Property.objects.none()).order_by("name")
        self.fields["category"].queryset = ExpenseCategory.objects.filter(is_active=True).order_by("sort_order", "name")


class ExpenseVoidForm(LocalizedFormMixin, forms.Form):
    reason = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}))


class RecurringExpenseForm(LocalizedFormMixin, forms.ModelForm):
    class Meta:
        model = RecurringExpense
        fields = ("property", "category", "amount", "currency", "vendor", "description", "notes", "billing_interval", "billing_unit", "start_date", "ends_on")
        widgets = {"start_date": forms.DateInput(attrs={"type": "date"}), "ends_on": forms.DateInput(attrs={"type": "date"}), "notes": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, properties=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["property"].queryset = (properties if properties is not None else Property.objects.none()).order_by("name")
        self.fields["category"].queryset = ExpenseCategory.objects.filter(is_active=True).order_by("sort_order", "name")


class ExpenseCategoryForm(LocalizedFormMixin, forms.ModelForm):
    class Meta:
        model = ExpenseCategory
        fields = ("name", "slug", "sort_order", "is_active")


class ExpenseImportForm(LocalizedFormMixin, forms.Form):
    file = forms.FileField(help_text=_("CSV columns: property, category, amount, currency, incurred_on, vendor, reference, description, notes."))


class UtilityMeterForm(LocalizedFormMixin, forms.ModelForm):
    class Meta:
        model = UtilityMeter
        fields = ("unit", "kind", "utility_name", "serial_number", "unit_of_measure", "rate", "currency", "is_active")

    def __init__(self, *args, properties=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["unit"].queryset = Unit.objects.filter(property__in=(properties if properties is not None else Property.objects.none())).select_related("property").order_by("property__name", "name")


class UtilityReadingForm(LocalizedFormMixin, forms.Form):
    reading_date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    current_reading = forms.DecimalField(max_digits=14, decimal_places=3, min_value=0)
    notes = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))


class UtilityCorrectionForm(LocalizedFormMixin, forms.Form):
    adjustment_consumption = forms.DecimalField(max_digits=14, decimal_places=3)
    notes = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}))


class InspectionTemplateForm(LocalizedFormMixin, forms.ModelForm):
    checklist = forms.CharField(widget=forms.Textarea(attrs={"rows": 8}), help_text=_("One checklist item per line."))
    class Meta:
        model = InspectionTemplate
        fields = ("name", "description", "inspection_type", "is_active", "checklist")


class InspectionCreateForm(LocalizedFormMixin, forms.Form):
    template = forms.ModelChoiceField(queryset=InspectionTemplate.objects.none())
    property = forms.ModelChoiceField(queryset=Property.objects.none())
    unit = forms.ModelChoiceField(queryset=Unit.objects.none(), required=False)
    lease = forms.ModelChoiceField(queryset=__import__("properties.models", fromlist=["Lease"]).Lease.objects.none(), required=False)
    inspection_date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    notes = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))

    def __init__(self, *args, properties=None, **kwargs):
        super().__init__(*args, **kwargs)
        properties = properties if properties is not None else Property.objects.none()
        self.fields["template"].queryset = InspectionTemplate.objects.filter(is_active=True)
        self.fields["property"].queryset = properties
        self.fields["unit"].queryset = Unit.objects.filter(property__in=properties)
        self.fields["lease"].queryset = __import__("properties.models", fromlist=["Lease"]).Lease.objects.filter(property__in=properties)


class InspectionPhotoForm(LocalizedFormMixin, forms.Form):
    file = forms.ImageField()
    caption = forms.CharField(max_length=200, required=False)


class MaintenanceTicketForm(LocalizedFormMixin, forms.ModelForm):
    block_unit = forms.BooleanField(required=False, help_text=_("Set the unit to maintenance until this ticket is resolved or cancelled."))
    attachment = forms.FileField(required=False)

    class Meta:
        model = MaintenanceTicket
        fields = ("property", "unit", "location", "title", "description", "priority")
        widgets = {"description": forms.Textarea(attrs={"rows": 4})}

    def __init__(self, *args, properties=None, **kwargs):
        super().__init__(*args, **kwargs)
        properties = properties if properties is not None else Property.objects.none()
        self.fields["property"].queryset = properties.order_by("name")
        self.fields["unit"].queryset = Unit.objects.filter(property__in=properties, archived_at__isnull=True).select_related("property").order_by("property__name", "name")

    def clean(self):
        data = super().clean()
        if data.get("unit") and data.get("property") and data["unit"].property_id != data["property"].pk:
            self.add_error("unit", _("The unit must belong to the selected property."))
        if data.get("block_unit") and not data.get("unit"):
            self.add_error("block_unit", _("Choose a unit before blocking it."))
        return data


class MaintenanceUpdateForm(LocalizedFormMixin, forms.ModelForm):
    class Meta:
        model = MaintenanceTicket
        fields = ("title", "description", "priority", "assigned_to", "estimated_cost", "actual_cost", "scheduled_for")
        widgets = {"description": forms.Textarea(attrs={"rows": 4}), "scheduled_for": forms.DateTimeInput(attrs={"type": "datetime-local"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["assigned_to"].queryset = get_user_model().objects.filter(is_active=True).order_by("first_name", "username")


class MaintenanceTransitionForm(LocalizedFormMixin, forms.Form):
    status = forms.ChoiceField(choices=MaintenanceTicket.Status.choices)
    notes = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))


class MaintenanceAttachmentForm(LocalizedFormMixin, forms.Form):
    file = forms.FileField()
    caption = forms.CharField(max_length=200, required=False)


class ReminderSettingsForm(LocalizedFormMixin, forms.ModelForm):
    overdue_intervals_text = forms.CharField(label=_("Overdue intervals"), help_text=_("Comma-separated day intervals, for example 1, 3, 7."))
    channels = forms.MultipleChoiceField(choices=(("database", "In-app"), ("email", "Email"), ("whatsapp", "WhatsApp"), ("log", "Application log")), widget=forms.CheckboxSelectMultiple)

    class Meta:
        model = ReminderSettings
        fields = ("enabled", "days_before", "overdue_intervals_text", "channels", "lease_expiration_days", "upcoming_template", "due_template", "overdue_template")
        widgets = {"upcoming_template": forms.Textarea(attrs={"rows": 3}), "due_template": forms.Textarea(attrs={"rows": 3}), "overdue_template": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields["overdue_intervals_text"].initial = ", ".join(str(value) for value in self.instance.overdue_intervals)
            self.fields["channels"].initial = self.instance.channels

    def clean_overdue_intervals_text(self):
        raw = self.cleaned_data["overdue_intervals_text"]
        try:
            values = sorted(set(int(value.strip()) for value in raw.split(",") if value.strip()))
        except ValueError as error:
            raise forms.ValidationError(_("Use comma-separated whole numbers.")) from error
        if not values or any(value < 1 for value in values):
            raise forms.ValidationError(_("Add at least one positive day interval."))
        return values

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.overdue_intervals = self.cleaned_data["overdue_intervals_text"]
        instance.channels = self.cleaned_data["channels"]
        if commit:
            instance.full_clean()
            instance.save()
        return instance
