from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend
from django.core.mail.backends.console import EmailBackend as ConsoleEmailBackend
from django.core.mail.backends.smtp import EmailBackend as SmtpEmailBackend


class DatabaseEmailBackend(BaseEmailBackend):
    """Resolve the active mail transport from encrypted database settings."""

    def _connection(self):
        from accounts.models import AppSetting
        from .models import Integration

        integration = Integration.objects.filter(kind=Integration.Kind.EMAIL, is_enabled=True).order_by("pk").first()
        if not integration:
            if not settings.DEBUG:
                raise ValueError("No enabled email integration is configured.")
            return ConsoleEmailBackend(fail_silently=self.fail_silently)
        if integration.provider == "console":
            if not settings.DEBUG:
                raise ValueError("The console email provider is disabled in production. Configure SMTP in settings.")
            return ConsoleEmailBackend(fail_silently=self.fail_silently)
        if integration.provider != "smtp":
            raise ValueError(f"Unsupported email provider: {integration.provider}")
        config = integration.configuration
        password = ""
        if integration.secret_reference:
            secret = AppSetting.objects.filter(key=integration.secret_reference).first()
            password = secret.get_value() if secret else ""
        return SmtpEmailBackend(
            host=config.get("host", ""), port=int(config.get("port", 587)),
            username=config.get("username", ""), password=password,
            use_tls=bool(config.get("use_tls")), use_ssl=bool(config.get("use_ssl")),
            timeout=int(config.get("timeout", 10)), fail_silently=self.fail_silently,
        )

    def send_messages(self, email_messages):
        messages = list(email_messages)
        if not messages:
            return 0
        try:
            connection = self._connection()
            from_email = settings.DEFAULT_FROM_EMAIL
            try:
                from .models import Integration
                integration = Integration.objects.filter(kind=Integration.Kind.EMAIL, is_enabled=True).order_by("pk").first()
                if integration:
                    from_email = integration.configuration.get("from_email") or from_email
            except Exception:
                pass
            for message in messages:
                if not message.from_email or message.from_email == settings.DEFAULT_FROM_EMAIL:
                    message.from_email = from_email
            return connection.send_messages(messages)
        except Exception:
            if self.fail_silently:
                return 0
            raise
