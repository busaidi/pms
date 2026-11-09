from contextvars import ContextVar
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from django.db.models.fields.files import FieldFile


_context = ContextVar("audit_context", default=None)
SENSITIVE_PARTS = ("password", "secret", "token", "credential", "public_key")


def begin(actor, ip_address=None):
    return _context.set({"actor_id": getattr(actor, "pk", None), "ip_address": ip_address})


def end(token):
    _context.reset(token)


def current():
    return _context.get()


def _json_value(value):
    if isinstance(value, (datetime, date, Decimal, UUID)):
        return str(value)
    if isinstance(value, FieldFile):
        return value.name
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items() if not any(part in str(key).lower() for part in SENSITIVE_PARTS)}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def snapshot(instance):
    values = {}
    for field in instance._meta.concrete_fields:
        if any(part in field.name.lower() for part in SENSITIVE_PARTS):
            continue
        values[field.name] = _json_value(getattr(instance, field.attname, None))
    return values
