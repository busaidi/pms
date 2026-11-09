from django.apps import AppConfig


class DataTransferConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "data_transfer"
    verbose_name = "Legacy data migration"
