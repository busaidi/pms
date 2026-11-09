"""Fast, deterministic test settings."""

from .development import *  # noqa: F403

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",
    "accounts.hashers.LaravelBCryptPasswordHasher",
]
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
