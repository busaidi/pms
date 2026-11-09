import base64
import hashlib
import secrets

from cryptography.fernet import Fernet
from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password


def _fernet():
    key = base64.urlsafe_b64encode(hashlib.sha256(settings.SECRET_KEY.encode()).digest())
    return Fernet(key)


def encrypt(value):
    return _fernet().encrypt(value.encode()).decode()


def decrypt(value):
    return _fernet().decrypt(value.encode()).decode()


def generate_recovery_codes(count=8):
    raw_codes = [f"{secrets.token_hex(3)}-{secrets.token_hex(3)}" for _ in range(count)]
    return raw_codes, [make_password(code) for code in raw_codes]


def consume_recovery_code(user, raw_code):
    from django.utils import timezone

    for recovery_code in user.recovery_codes.filter(used_at__isnull=True):
        if check_password(raw_code, recovery_code.code_hash):
            recovery_code.used_at = timezone.now()
            recovery_code.save(update_fields=("used_at",))
            return True
    return False
