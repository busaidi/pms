from datetime import timedelta

import pyotp
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core import mail
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from properties.models import Property

from .access import properties_for_user, user_has_capability
from .models import AppSetting, AuditLog, Capability, Invitation, Passkey, PropertyAccess, RecoveryCode, UserProfile
from .permissions import PERMISSIONS
from .security import decrypt


class RoleParityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("sync_roles", verbosity=0)
        cls.user = get_user_model().objects.create_user("staff", password="test-pass")

    def test_all_openkos_capabilities_are_synchronized(self):
        self.assertEqual(Capability.objects.count(), 62)
        self.assertSetEqual(set(Capability.objects.values_list("name", flat=True)), set(PERMISSIONS))

    def test_role_allow_and_deny(self):
        self.user.groups.add(Group.objects.get(name="finance-staff"))
        self.assertTrue(user_has_capability(self.user, "financials.view"))
        self.assertFalse(user_has_capability(self.user, "properties.update"))

    def test_every_persona_has_expected_allow_and_deny(self):
        cases = {
            "owner": ("roles.delete", None),
            "admin": ("users.update", "roles.delete"),
            "staff": ("tenants.view", "financials.view"),
            "finance-staff": ("financials.view", "properties.update"),
            "front-desk": ("tenants.create", "expenses.delete"),
            "maintenance-staff": ("maintenance-tickets.update", "payments.verify"),
            "property-manager": ("leases.create", "users.update"),
            "tenant": (None, "dashboard.view"),
            "applicant": (None, "dashboard.view"),
        }
        for role_name, (allowed, denied) in cases.items():
            user = get_user_model().objects.create_user(f"persona-{role_name}")
            user.groups.add(Group.objects.get(name=role_name))
            if allowed:
                self.assertTrue(user_has_capability(user, allowed), role_name)
            if denied:
                self.assertFalse(user_has_capability(user, denied), role_name)

    def test_property_scoped_role_only_returns_assigned_property(self):
        assigned = Property.objects.create(name="Assigned", address="Muscat")
        Property.objects.create(name="Hidden", address="Muscat")
        PropertyAccess.objects.create(user=self.user, property=assigned, group=Group.objects.get(name="property-manager"))
        self.assertEqual(list(properties_for_user(self.user)), [assigned])


class InvitationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("sync_roles", verbosity=0)
        cls.owner = get_user_model().objects.create_superuser("owner", "owner@example.test", "test-pass")

    def test_invitation_stores_hash_and_creates_role_membership(self):
        self.client.force_login(self.owner)
        response = self.client.post(reverse("team_invite"), {"email": "new@example.test", "role": Group.objects.get(name="staff").pk, "scope_property": ""})
        self.assertEqual(response.status_code, 200)
        invitation = Invitation.objects.get(email="new@example.test")
        link = response.context["invitation_link"]
        raw_token = link.rsplit("/", 2)[-2]
        self.assertEqual(len(invitation.token), 64)
        self.assertNotEqual(invitation.token, raw_token)
        response = self.client.post(reverse("invitation_accept", args=(raw_token,)), {"first_name": "New", "last_name": "User", "new_password1": "A-secure-test-password-42", "new_password2": "A-secure-test-password-42"})
        self.assertRedirects(response, reverse("login"))
        user = get_user_model().objects.get(email="new@example.test")
        self.assertTrue(user.groups.filter(name="staff").exists())


class TwoFactorTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("secure", "secure@example.test", "test-pass")
        self.client.force_login(self.user)

    def test_setup_encrypts_secret_and_requires_challenge(self):
        self.client.get(reverse("two_factor_setup"))
        secret = self.client.session["two_factor_setup_secret"]
        response = self.client.post(reverse("two_factor_setup"), {"code": pyotp.TOTP(secret).now()})
        self.assertRedirects(response, reverse("two_factor_recovery_codes"))
        self.user.pms_profile.refresh_from_db()
        self.assertTrue(self.user.pms_profile.two_factor_enabled)
        self.assertNotEqual(self.user.pms_profile.two_factor_secret, secret)
        self.assertEqual(decrypt(self.user.pms_profile.two_factor_secret), secret)
        self.assertEqual(self.user.recovery_codes.count(), 8)
        session = self.client.session
        session.pop("two_factor_verified", None)
        session.save()
        self.assertRedirects(self.client.get(reverse("account_profile")), reverse("two_factor_challenge"))


class ProfileLanguageTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            "language-user",
            "language@example.test",
            "test-pass",
            first_name="Language",
        )
        self.client.force_login(self.user)

    def test_saved_profile_language_overrides_stale_cookie(self):
        profile = UserProfile.objects.get(user=self.user)
        profile.preferred_language = "ar"
        profile.save(update_fields=("preferred_language",))
        self.client.cookies[settings.LANGUAGE_COOKIE_NAME] = "en"

        response = self.client.get(reverse("account_profile"))

        self.assertContains(response, '<html lang="ar" dir="rtl">')
        self.assertContains(response, "الملف الشخصي")

    def test_profile_save_updates_language_cookie_immediately(self):
        self.client.cookies[settings.LANGUAGE_COOKIE_NAME] = "en"

        response = self.client.post(
            reverse("account_profile"),
            {
                "first_name": "Language",
                "last_name": "User",
                "email": "language@example.test",
                "phone": "",
                "preferred_language": "ar",
                "timezone": "Asia/Muscat",
            },
        )

        self.assertRedirects(response, reverse("account_profile"), fetch_redirect_response=False)
        self.assertEqual(response.cookies[settings.LANGUAGE_COOKIE_NAME].value, "ar")
        self.assertEqual(UserProfile.objects.get(user=self.user).preferred_language, "ar")

        translated = self.client.get(reverse("account_profile"))
        self.assertContains(translated, '<html lang="ar" dir="rtl">')


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class PasswordResetTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            "reset-user", "reset@example.test", "old-password"
        )

    def test_reset_form_is_visible_while_signed_in(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("password_reset"))

        self.assertContains(response, "Find your account")
        self.assertContains(response, 'name="email"')

    def test_reset_request_emails_a_working_link(self):
        response = self.client.post(
            reverse("password_reset"), {"email": self.user.email}
        )

        self.assertRedirects(response, reverse("password_reset_done"))
        self.assertEqual(len(mail.outbox), 1)
        reset_path = mail.outbox[0].body.splitlines()[3]
        confirmation = self.client.get(reset_path)
        self.assertRedirects(confirmation, confirmation.url)
        confirmation = self.client.get(confirmation.url)
        self.assertContains(confirmation, "Set your new password")


class SecurityRecordTests(TestCase):
    def test_audit_log_is_immutable(self):
        log = AuditLog.objects.create(action="test", summary="Created")
        log.summary = "Changed"
        with self.assertRaises(ValueError):
            log.save()

    def test_expired_invitation_is_unusable(self):
        owner = get_user_model().objects.create_user("owner")
        group = Group.objects.create(name="test")
        invitation = Invitation(email="expired@example.test", group=group, invited_by=owner, expires_at=timezone.now() - timedelta(seconds=1))
        invitation.issue_token()
        invitation.save()
        self.assertFalse(invitation.is_usable)

    def test_secret_setting_is_encrypted_at_rest(self):
        setting = AppSetting(key="mail.password", group="mail", value_type=AppSetting.ValueType.SECRET, is_secret=True)
        setting.set_value("private-value")
        setting.save()
        setting.refresh_from_db()
        self.assertNotIn("private-value", str(setting.value))
        self.assertEqual(setting.get_value(), "private-value")


class AccountLifecycleTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("account-user", "account@example.test", "old-password")
        self.client.force_login(self.user)

    def test_password_change_keeps_session_and_marks_confirmation_fresh(self):
        response = self.client.post(reverse("password_change"), {"old_password": "old-password", "new_password1": "A-new-password-42", "new_password2": "A-new-password-42"})
        self.assertRedirects(response, reverse("account_security"))
        self.assertTrue(self.client.get(reverse("password_confirmation_status")).json()["confirmed"])
        self.assertEqual(self.client.get(reverse("account_profile")).status_code, 200)

    def test_passkey_delete_requires_recent_password_confirmation(self):
        passkey = Passkey.objects.create(user=self.user, name="Laptop", credential_id=b"credential", public_key=b"public", sign_count=0)
        response = self.client.post(reverse("passkey_delete", args=(passkey.pk,)))
        self.assertRedirects(response, f"{reverse('confirm_password')}?next={reverse('account_security')}", fetch_redirect_response=False)
        self.client.post(reverse("confirm_password"), {"password": "old-password", "next": reverse("account_security")})
        self.client.post(reverse("passkey_delete", args=(passkey.pk,)))
        self.assertFalse(Passkey.objects.filter(pk=passkey.pk).exists())

    def test_recovery_code_regeneration_replaces_existing_codes(self):
        profile = self.user.pms_profile
        profile.two_factor_enabled = True
        profile.save(update_fields=("two_factor_enabled",))
        RecoveryCode.objects.create(user=self.user, code_hash="old")
        session = self.client.session
        session["two_factor_verified"] = True
        session.save()
        self.client.post(reverse("confirm_password"), {"password": "old-password", "next": reverse("account_security")})
        response = self.client.post(reverse("recovery_codes_regenerate"))
        self.assertRedirects(response, reverse("two_factor_recovery_codes"), fetch_redirect_response=False)
        self.assertEqual(self.user.recovery_codes.count(), 8)
        self.assertFalse(self.user.recovery_codes.filter(code_hash="old").exists())

    def test_self_deactivation_preserves_user_record(self):
        response = self.client.post(reverse("account_deactivate"), {"password": "old-password"})
        self.assertRedirects(response, reverse("login"))
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)

    def test_model_update_audit_contains_before_and_after(self):
        self.client.post(reverse("account_profile"), {"first_name": "Changed", "last_name": "", "email": self.user.email, "phone": "", "preferred_language": "en", "timezone": "Asia/Muscat"})
        log = AuditLog.objects.filter(action="auth.user.updated", target_id=str(self.user.pk)).latest("created_at")
        self.assertEqual(log.changes["before"]["first_name"], "")
        self.assertEqual(log.changes["after"]["first_name"], "Changed")
