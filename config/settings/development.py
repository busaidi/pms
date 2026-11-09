"""Local developer settings. Never used by the systemd service."""

from .base import *  # noqa: F403

SECRET_KEY = "django-insecure-local-development-only"
DEBUG = True
ALLOWED_HOSTS = ["127.0.0.1", "localhost"]
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",  # noqa: F405
    }
}
