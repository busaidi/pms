"""Isolated PostgreSQL settings for browser workflow verification."""

import os

from .test import *  # noqa: F403
from .base import postgres_database


DATABASES = postgres_database()
DATABASES["default"]["NAME"] = os.environ.get("DJANGO_BROWSER_DB_NAME", "pms_browser")
DATABASES["default"]["CONN_MAX_AGE"] = 0
ALLOWED_HOSTS = ["127.0.0.1", "localhost"]
PASSKEY_RP_ID = "127.0.0.1"
PASSKEY_ORIGIN = "http://127.0.0.1:8765"
