from django import forms
from core.forms import LocalizedFormMixin

from properties.models import Lease

from .gateways import gateway_choices
from .models import Payment
from django.utils.translation import gettext_lazy as _


class StyledForm(LocalizedFormMixin, forms.Form):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")


class ManualInvoiceForm(StyledForm):
    lease = forms.ModelChoiceField(Lease.objects.none())
    issue_date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    due_date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    description = forms.CharField(max_length=255)
    amount = forms.DecimalField(max_digits=14, decimal_places=3, min_value=0.001)
    notes = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))

    def __init__(self, *args, leases=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["lease"].queryset = leases if leases is not None else Lease.objects.none()

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("issue_date") and cleaned.get("due_date") and cleaned["due_date"] < cleaned["issue_date"]:
            self.add_error("due_date", _("Due date must be on or after issue date."))
        return cleaned


class PaymentForm(StyledForm):
    amount = forms.DecimalField(max_digits=14, decimal_places=3, min_value=0.001)
    method = forms.ChoiceField(choices=[choice for choice in Payment.Method.choices if choice[0] != Payment.Method.GATEWAY])
    payment_date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    proof = forms.FileField(required=False)
    notes = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))

    def clean_proof(self):
        proof = self.cleaned_data.get("proof")
        if not proof:
            return proof
        extension = proof.name.rsplit(".", 1)[-1].lower() if "." in proof.name else ""
        if extension not in {"pdf", "jpg", "jpeg", "png"}:
            raise forms.ValidationError(_("Upload a PDF or image proof."))
        if proof.size > 10 * 1024 * 1024:
            raise forms.ValidationError(_("Payment proof cannot exceed 10 MB."))
        return proof


class PaymentReviewForm(StyledForm):
    decision = forms.ChoiceField(choices=(("confirm", "Confirm"), ("reject", "Reject")))
    notes = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))


class GatewayForm(StyledForm):
    gateway = forms.ChoiceField(choices=())

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["gateway"].choices = gateway_choices()


class GatewaySettingsForm(StyledForm):
    is_enabled = forms.BooleanField(required=False, initial=True)
    bank_name = forms.CharField(max_length=120, required=False)
    account_name = forms.CharField(max_length=120, required=False)
    iban = forms.CharField(max_length=80, required=False)
    instructions = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 4}))
    secret_reference = forms.CharField(max_length=255, required=False, help_text=_("Environment variable name for signed provider webhooks; never enter the secret itself."))
