from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"
    verbose_name = "Platform"

    def ready(self):
        from .i18n import localize_model_metadata

        localize_model_metadata()
