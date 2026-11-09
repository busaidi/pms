from django import forms
from core.forms import LocalizedFormMixin

from billing.forms import PaymentForm
from properties.models import Lease
from django.utils.translation import gettext_lazy as _


class PortalPaymentForm(PaymentForm):
    proof = forms.FileField(help_text=_("Upload a PDF, JPG, or PNG transfer receipt."))


class PortalMaintenanceForm(LocalizedFormMixin, forms.Form):
    lease = forms.ModelChoiceField(queryset=Lease.objects.none())
    location = forms.CharField(max_length=255, required=False)
    title = forms.CharField(max_length=180)
    description = forms.CharField(widget=forms.Textarea(attrs={"rows": 4}))
    priority = forms.ChoiceField(choices=(("low", "Low"), ("medium", "Medium"), ("high", "High"), ("urgent", "Urgent")))
    attachment = forms.FileField(required=False)

    def __init__(self, *args, leases=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["lease"].queryset = leases if leases is not None else Lease.objects.none()

    def clean_attachment(self):
        attachment = self.cleaned_data.get("attachment")
        if not attachment:
            return attachment
        extension = attachment.name.rsplit(".", 1)[-1].lower() if "." in attachment.name else ""
        if extension not in {"pdf", "jpg", "jpeg", "png", "webp"}:
            raise forms.ValidationError(_("Upload a PDF or image attachment."))
        if attachment.size > 10 * 1024 * 1024:
            raise forms.ValidationError(_("Attachments cannot exceed 10 MB."))
        return attachment
