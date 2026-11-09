"""Production settings for omanskylight.com."""

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F403
from .base import postgres_database

secret_key_file = Path(os.environ.get("DJANGO_SECRET_KEY_FILE", "/etc/pms.secret"))
if os.environ.get("DJANGO_SECRET_KEY"):
    SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]
elif secret_key_file.is_file():
    SECRET_KEY = secret_key_file.read_text().strip()
else:
    raise ImproperlyConfigured("Set DJANGO_SECRET_KEY or DJANGO_SECRET_KEY_FILE")

DEBUG = False
ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get(
        "DJANGO_ALLOWED_HOSTS", "omanskylight.com,127.0.0.1,localhost"
    ).split(",")
    if host.strip()
]
CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get(
        "DJANGO_CSRF_TRUSTED_ORIGINS", "https://omanskylight.com"
    ).split(",")
    if origin.strip()
]
DATABASES = postgres_database()
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
LANGUAGE_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = int(os.environ.get("DJANGO_SECURE_HSTS_SECONDS", "31536000"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
PASSKEY_RP_ID = os.environ.get("PASSKEY_RP_ID", "omanskylight.com")
PASSKEY_ORIGIN = os.environ.get("PASSKEY_ORIGIN", "https://omanskylight.com")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"json": {"()": "core.logging.JsonFormatter"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "json"}},
    "root": {"handlers": ["console"], "level": os.environ.get("DJANGO_LOG_LEVEL", "INFO")},
    "loggers": {"django.server": {"handlers": ["console"], "level": "INFO", "propagate": False}},
}
