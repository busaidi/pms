from django import template
from django.template.defaultfilters import pluralize
from django.utils.translation import get_language


register = template.Library()


@register.filter
def locale_pluralize(value, argument="s"):
    """Avoid appending English suffixes to Arabic translated nouns."""
    if get_language() == "ar":
        return ""
    return pluralize(value, argument)
