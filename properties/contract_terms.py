"""Editable terms are sanitized content, never executable Django templates."""
import re
from functools import lru_cache
from pathlib import Path

import bleach
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils.html import strip_tags

from .models import ContractTermsTemplate

TAGS = {"p", "br", "h2", "h3", "strong", "b", "em", "i", "u", "s", "ol", "ul", "li", "blockquote"}


def clean_terms(value):
    if len(value) > 120000:
        raise ValidationError("نص القالب طويل جدًا؛ الحد الأقصى 120 ألف حرف.")
    value = re.sub(r"<(script|style|iframe)\b[^>]*>.*?</\1\s*>", "", value, flags=re.I | re.S)
    value = bleach.clean(value, tags=TAGS, attributes={}, strip=True, strip_comments=True)
    if not strip_tags(value).replace("&nbsp;", " ").strip():
        raise ValidationError("أدخل نص الشروط والأحكام.")
    return value


@lru_cache(maxsize=1)
def approved_terms():
    source = (Path(settings.BASE_DIR) / "templates/properties/contracts/terms_v6.html").read_text(encoding="utf-8")
    blocks = re.findall(r'<h3>.*?</h3>|<p(?: class="small")?>.*?</p>', source, re.S)
    return clean_terms("\n".join(blocks))


def default_terms(property_obj):
    template, _ = ContractTermsTemplate.objects.get_or_create(
        property=property_obj, is_default=True,
        defaults={"name": "شروط الإقامة المعتمدة", "body": approved_terms()},
    )
    return template


def terms_snapshot(lease):
    template = lease.terms_template or default_terms(lease.property)
    if template.property_id != lease.property_id:
        raise ValidationError("قالب الشروط لا يتبع عقار العقد.")
    return {"id": template.pk, "name": template.name, "revision": template.revision, "html": clean_terms(template.body)}
