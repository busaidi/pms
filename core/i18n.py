from django.apps import apps
from django.utils.translation import gettext_lazy


LOCAL_APPS = {
    "accounts",
    "billing",
    "data_transfer",
    "integrations",
    "operations",
    "portal",
    "properties",
}


def _localized_choices(choices):
    localized = []
    for value, label in choices:
        if isinstance(label, (list, tuple)):
            label = _localized_choices(label)
        else:
            label = gettext_lazy(str(label))
        localized.append((value, label))
    return localized


def localize_model_metadata():
    """Make generated model/form labels and choice displays translatable."""
    for model in apps.get_models():
        if model._meta.app_label not in LOCAL_APPS:
            continue
        if getattr(model._meta, "_pms_localized", False):
            continue
        model._meta.verbose_name = gettext_lazy(str(model._meta.verbose_name))
        model._meta.verbose_name_plural = gettext_lazy(str(model._meta.verbose_name_plural))
        for field in model._meta.get_fields():
            if hasattr(field, "verbose_name") and field.verbose_name:
                field.verbose_name = gettext_lazy(str(field.verbose_name))
            if hasattr(field, "help_text") and field.help_text:
                field.help_text = gettext_lazy(str(field.help_text))
            if getattr(field, "choices", None):
                field.choices = _localized_choices(field.choices)
        model._meta._pms_localized = True
