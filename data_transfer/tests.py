import bcrypt

from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password
from django.test import TestCase, override_settings

from .models import LegacyRecordMap


class LaravelPasswordHasherTests(TestCase):
    @override_settings(
        PASSWORD_HASHERS=[
            "django.contrib.auth.hashers.PBKDF2PasswordHasher",
            "accounts.hashers.LaravelBCryptPasswordHasher",
        ]
    )
    def test_laravel_bcrypt_hash_verifies_and_upgrades(self):
        raw = "Legacy-password-123!"
        laravel = bcrypt.hashpw(raw.encode(), bcrypt.gensalt()).decode().replace("$2b$", "$2y$", 1)
        user = get_user_model().objects.create(username="legacy", password=f"laravel_bcrypt${laravel}")
        self.assertTrue(check_password(raw, user.password))
        self.assertTrue(user.check_password(raw))
        user.refresh_from_db()
        self.assertTrue(user.password.startswith("pbkdf2_sha256$"))

    def test_legacy_mapping_is_unique_and_restartable(self):
        LegacyRecordMap.objects.create(source="openkos", source_table="users", source_id="1", target_model="auth.User", target_id="10")
        mapping, created = LegacyRecordMap.objects.update_or_create(source="openkos", source_table="users", source_id="1", defaults={"target_model": "auth.User", "target_id": "10", "checksum": "new"})
        self.assertFalse(created)
        self.assertEqual(mapping.checksum, "new")
