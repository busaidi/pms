from django import forms
from django.utils.translation import gettext_lazy as _

from .models import LeaseContractProfile, ContractTermsTemplate
from .contract_terms import clean_terms


class ContractTermsForm(forms.ModelForm):
    expected_revision = forms.IntegerField(widget=forms.HiddenInput, required=False)

    class Meta:
        model = ContractTermsTemplate
        fields = ("name", "body", "is_active")
        labels = {"name": "اسم القالب", "body": "الشروط والأحكام", "is_active": "متاح للاختيار في العقود"}
        widgets = {"body": forms.Textarea(attrs={"rows": 20, "data-terms-editor": ""})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["expected_revision"].initial = self.instance.revision if self.instance.pk else 0
        if self.instance.is_default:
            self.fields["is_active"].disabled = True
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")

    def clean_body(self):
        return clean_terms(self.cleaned_data["body"])


class ContractTermsPreviewForm(forms.Form):
    name = forms.CharField(max_length=160, required=False)
    body = forms.CharField()

    def clean_body(self):
        return clean_terms(self.cleaned_data["body"])


class ContractTemplateSelectionForm(forms.Form):
    terms_template = forms.ModelChoiceField(ContractTermsTemplate.objects.none(), label="قالب الشروط والأحكام")

    def __init__(self, *args, lease, **kwargs):
        super().__init__(*args, **kwargs)
        from .contract_terms import default_terms
        default = default_terms(lease.property)
        self.fields["terms_template"].queryset = ContractTermsTemplate.objects.filter(property=lease.property, is_active=True)
        self.fields["terms_template"].initial = lease.terms_template_id or default.pk
        self.fields["terms_template"].widget.attrs["class"] = "form-control"


class ContractProfileForm(forms.ModelForm):
    class Meta:
        model = LeaseContractProfile
        fields = ("display_name", "location", "lessor_name", "lessor_phone", "lessor_email",
                  "plot_number", "building_number", "block_number", "road_number")
        labels = {"display_name": _("Property name on contract"), "location": _("Contract location"),
                  "lessor_name": _("Lessor name"), "lessor_phone": _("Lessor phone"),
                  "lessor_email": _("Lessor email"), "plot_number": _("Plot number"),
                  "building_number": _("Building number"), "block_number": _("Block number"),
                  "road_number": _("Road number")}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["lessor_name"].required = True
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-control"
