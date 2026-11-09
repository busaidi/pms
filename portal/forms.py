from django import forms
from core.forms import LocalizedFormMixin

from .models import Application


class ApplicationForm(LocalizedFormMixin, forms.ModelForm):
    class Meta:
        model = Application
        fields = ("full_name", "email", "phone", "nationality", "desired_move_in", "intended_move_in_timeframe", "occupants", "monthly_income", "message")
        widgets = {
            "desired_move_in": forms.DateInput(attrs={"type": "date"}),
            "message": forms.Textarea(attrs={"rows": 4}),
        }


class ApplicationReviewForm(LocalizedFormMixin, forms.Form):
    status = forms.ChoiceField(choices=(("reviewing", "Reviewing"), ("accepted", "Accepted"), ("rejected", "Rejected"), ("withdrawn", "Withdrawn")))
    operator_notes = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))
    applicant_feedback = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))


class PublicPortalSettingsForm(LocalizedFormMixin, forms.Form):
    site_name = forms.CharField(max_length=120)
    homepage_title = forms.CharField(max_length=180)
    homepage_description = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}))
    social_image_url = forms.URLField(required=False)
    logo_url = forms.URLField(required=False)
    favicon_url = forms.URLField(required=False)
