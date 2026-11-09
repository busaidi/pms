"""Fast, deterministic test settings."""

from .development import *  # noqa: F403

# Keep the fast test profile independent of the development database.
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",
    "accounts.hashers.LaravelBCryptPasswordHasher",
]
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
