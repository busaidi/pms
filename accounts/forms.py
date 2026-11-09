from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import SetPasswordForm
from django.contrib.auth.models import Group
from core.forms import LocalizedFormMixin

from properties.models import Property

from .models import AppSetting, Capability, Invitation, UserProfile
from django.utils.translation import gettext_lazy as _


class ProfileForm(LocalizedFormMixin, forms.Form):
    first_name = forms.CharField(max_length=150)
    last_name = forms.CharField(max_length=150, required=False)
    email = forms.EmailField()
    phone = forms.CharField(max_length=30, required=False)
    preferred_language = forms.ChoiceField(choices=(("en", "English"), ("ar", "Arabic")))
    timezone = forms.ChoiceField(choices=(("Asia/Muscat", "Asia/Muscat"), ("UTC", "UTC")))


class InvitationForm(LocalizedFormMixin, forms.Form):
    email = forms.EmailField()
    role = forms.ModelChoiceField(queryset=Group.objects.filter(pms_profile__is_active=True).exclude(name="owner"))
    scope_property = forms.ModelChoiceField(queryset=Property.objects.filter(is_active=True), required=False)

    def clean_email(self):
        email = self.cleaned_data["email"].lower()
        if get_user_model().objects.filter(email__iexact=email).exists():
            raise forms.ValidationError(_("A user with this email already exists."))
        if Invitation.objects.filter(email__iexact=email, status=Invitation.Status.PENDING).exists():
            raise forms.ValidationError(_("A pending invitation already exists."))
        return email


class InvitationAcceptForm(LocalizedFormMixin, SetPasswordForm):
    first_name = forms.CharField(max_length=150)
    last_name = forms.CharField(max_length=150, required=False)


class RoleForm(LocalizedFormMixin, forms.Form):
    name = forms.SlugField(max_length=150)
    label = forms.CharField(max_length=100)
    description = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), required=False)
    color = forms.CharField(max_length=7, initial="#087a78")
    capabilities = forms.ModelMultipleChoiceField(
        queryset=Capability.objects.all(), widget=forms.CheckboxSelectMultiple
    )


class UserManageForm(LocalizedFormMixin, forms.Form):
    first_name = forms.CharField(max_length=150)
    last_name = forms.CharField(max_length=150, required=False)
    email = forms.EmailField()
    is_active = forms.BooleanField(required=False)
    roles = forms.ModelMultipleChoiceField(queryset=Group.objects.filter(pms_profile__is_active=True).exclude(name="owner"))
    properties = forms.ModelMultipleChoiceField(queryset=Property.objects.filter(is_active=True), required=False)


class GeneralSettingsForm(LocalizedFormMixin, forms.Form):
    organization_name = forms.CharField(max_length=160)
    currency = forms.ChoiceField(choices=(("OMR", "Omani rial (OMR)"),))
    locale = forms.ChoiceField(choices=(("en", "English"), ("ar", "Arabic")))
    support_email = forms.EmailField(required=False)

    @classmethod
    def initial_values(cls):
        def value(key, default):
            setting = AppSetting.objects.filter(key=key).first()
            return setting.value.get("value", default) if setting else default
        return {
            "organization_name": value("general.organization_name", "Oman Skylight"),
            "currency": value("general.currency_code", "OMR"),
            "locale": value("general.locale", "en"),
            "support_email": value("general.support_email", ""),
        }

    def save(self):
        for field, value in self.cleaned_data.items():
            AppSetting.objects.update_or_create(
                key=f"general.{field}" if field != "currency" else "general.currency_code",
                defaults={"group": "general", "value": {"value": value}},
            )


class TwoFactorCodeForm(LocalizedFormMixin, forms.Form):
    code = forms.CharField(max_length=20, help_text=_("Enter an authenticator or recovery code."))


class PasswordConfirmationForm(LocalizedFormMixin, forms.Form):
    password = forms.CharField(label=_("Current password"), widget=forms.PasswordInput)

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_password(self):
        password = self.cleaned_data["password"]
        if not self.user.check_password(password):
            raise forms.ValidationError(_("The password is incorrect."))
        return password
