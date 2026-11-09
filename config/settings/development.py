"""Local developer settings. Never used by the systemd service."""

import json
import os

from .base import *  # noqa: F403
from .base import BASE_DIR, postgres_database

SECRET_KEY = "django-insecure-local-development-only"
DEBUG = True
ALLOWED_HOSTS = ["127.0.0.1", "localhost"]
# Restored production data must not select a real SMTP transport locally.
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
# Machine-local credentials are ignored by Git. Environment variables take priority.
local_database_file = BASE_DIR / ".local-postgres" / "connection.json"
if local_database_file.is_file():
    local_database = json.loads(local_database_file.read_text(encoding="utf-8"))
    for key, value in local_database["environment"].items():
        os.environ.setdefault(key, value)
    # The pure-Python psycopg driver needs the installed PostgreSQL client library.
    if os.name == "nt" and local_database.get("bin"):
        os.environ["PATH"] = local_database["bin"] + os.pathsep + os.environ.get("PATH", "")

DATABASES = postgres_database()
DATABASES["default"]["HOST"] = os.environ.get("DJANGO_DB_HOST", "127.0.0.1")
