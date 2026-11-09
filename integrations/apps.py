from django.apps import AppConfig


class IntegrationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "integrations"
    verbose_name = "Integrations and extensions"

    def ready(self):
        from .registry import discover_extensions
        discover_extensions()
