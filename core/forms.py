from django import forms
from django.forms.utils import pretty_name
from django.utils.translation import gettext_lazy


class LocalizedFormMixin:
    """Localize declared labels, help text, empty labels, and static choices."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            field.label = gettext_lazy(str(field.label or pretty_name(name)))
            if field.help_text:
                field.help_text = gettext_lazy(str(field.help_text))
            if isinstance(field, forms.ModelChoiceField):
                if field.empty_label:
                    field.empty_label = gettext_lazy(str(field.empty_label))
                continue
            if getattr(field, "choices", None):
                field.choices = [
                    (value, gettext_lazy(str(label)))
                    for value, label in field.choices
                ]
