from django import forms
from django.conf import settings
from core.forms import LocalizedFormMixin

from .models import Integration
from django.utils.translation import gettext_lazy as _


class IntegrationForm(LocalizedFormMixin, forms.ModelForm):
    api_token = forms.CharField(required=False, widget=forms.PasswordInput(render_value=False), help_text=_("Stored encrypted. Leave blank to keep the current secret."))

    class Meta:
        model = Integration
        fields = ("name", "kind", "provider", "is_enabled", "configuration", "api_token")
        widgets = {"configuration": forms.Textarea(attrs={"rows": 6})}

    def clean_configuration(self):
        configuration = self.cleaned_data["configuration"]
        sensitive = {key for key in configuration if any(word in key.lower() for word in ("secret", "password", "token", "api_key", "apikey"))}
        if sensitive:
            raise forms.ValidationError(_("Move secret values to the encrypted API token field: ") + ", ".join(sorted(sensitive)))
        return configuration


class IntegrationTestForm(LocalizedFormMixin, forms.Form):
    recipient = forms.CharField(required=False, max_length=254, help_text=_("Email address or phone number used only for this test."))


class MailSettingsForm(LocalizedFormMixin, forms.Form):
    provider = forms.ChoiceField(choices=(("smtp", _("SMTP server")), ("console", _("Server log (development only)"))))
    is_enabled = forms.BooleanField(required=False)
    host = forms.CharField(max_length=255, required=False)
    port = forms.IntegerField(min_value=1, max_value=65535, initial=587)
    username = forms.CharField(max_length=255, required=False)
    password = forms.CharField(required=False, widget=forms.PasswordInput(render_value=False), help_text=_("Stored encrypted. Leave blank to keep the current password."))
    from_email = forms.EmailField(initial="noreply@omanskylight.com")
    use_tls = forms.BooleanField(required=False, initial=True)
    use_ssl = forms.BooleanField(required=False)
    timeout = forms.IntegerField(min_value=1, max_value=120, initial=10)

    def clean(self):
        values = super().clean()
        if values.get("use_tls") and values.get("use_ssl"):
            raise forms.ValidationError(_("Choose TLS or SSL, not both."))
        if values.get("provider") == "console" and values.get("is_enabled") and not settings.DEBUG:
            raise forms.ValidationError(_("The server log email provider cannot be enabled in production."))
        if values.get("provider") == "smtp" and values.get("is_enabled") and not values.get("host"):
            self.add_error("host", _("SMTP host is required when email is enabled."))
        return values


class WhatsAppSettingsForm(LocalizedFormMixin, forms.Form):
    provider = forms.ChoiceField(choices=(("log", _("Server log (development only)")), ("webhook", _("HTTPS webhook"))))
    is_enabled = forms.BooleanField(required=False)
    endpoint = forms.URLField(required=False)
    sender = forms.CharField(max_length=80, required=False)
    api_token = forms.CharField(required=False, widget=forms.PasswordInput(render_value=False), help_text=_("Stored encrypted. Leave blank to keep the current token."))

    def clean(self):
        values = super().clean()
        if values.get("provider") == "log" and values.get("is_enabled") and not settings.DEBUG:
            raise forms.ValidationError(_("The server log WhatsApp provider cannot be enabled in production."))
        if values.get("provider") == "webhook" and values.get("is_enabled") and not values.get("endpoint"):
            self.add_error("endpoint", _("Webhook endpoint is required when WhatsApp is enabled."))
        return values
