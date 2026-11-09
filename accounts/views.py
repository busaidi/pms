import base64
import hashlib
import json
import time
from datetime import timedelta

import pyotp
import qrcode
import qrcode.image.svg
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth import login as auth_login
from django.contrib.auth import logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group
from django.contrib.auth.forms import PasswordChangeForm, PasswordResetForm
from django.core.mail import send_mail
from django.db import transaction
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
from django.utils import timezone
from webauthn import generate_authentication_options, generate_registration_options, options_to_json, verify_authentication_response, verify_registration_response
from webauthn.helpers import base64url_to_bytes
from webauthn.helpers.structs import AuthenticatorSelectionCriteria, PublicKeyCredentialDescriptor, ResidentKeyRequirement, UserVerificationRequirement

from .access import capability_required
from .forms import GeneralSettingsForm, InvitationAcceptForm, InvitationForm, PasswordConfirmationForm, ProfileForm, RoleForm, TwoFactorCodeForm, UserManageForm
from .models import AuditLog, EmailVerificationToken, GroupProfile, Invitation, Passkey, PropertyAccess, RecoveryCode, UserProfile
from .security import consume_recovery_code, decrypt, encrypt, generate_recovery_codes
from django.utils.translation import gettext_lazy as _


@login_required
def profile(request):
    user = request.user
    profile_obj, _created = UserProfile.objects.get_or_create(user=user)
    initial = {"first_name": user.first_name, "last_name": user.last_name, "email": user.email, "phone": profile_obj.phone, "preferred_language": profile_obj.preferred_language, "timezone": profile_obj.timezone}
    form = ProfileForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        old_email = user.email
        user.first_name, user.last_name, user.email = form.cleaned_data["first_name"], form.cleaned_data["last_name"], form.cleaned_data["email"]
        user.save(update_fields=("first_name", "last_name", "email"))
        profile_obj.phone = form.cleaned_data["phone"]
        profile_obj.preferred_language = form.cleaned_data["preferred_language"]
        profile_obj.timezone = form.cleaned_data["timezone"]
        if old_email.lower() != user.email.lower():
            profile_obj.email_verified_at = None
        profile_obj.save()
        messages.success(request, _("Profile updated."))
        response = redirect("account_profile")
        response.set_cookie(
            settings.LANGUAGE_COOKIE_NAME,
            profile_obj.preferred_language,
            max_age=settings.LANGUAGE_COOKIE_AGE,
            path=settings.LANGUAGE_COOKIE_PATH,
            domain=settings.LANGUAGE_COOKIE_DOMAIN,
            secure=settings.LANGUAGE_COOKIE_SECURE,
            httponly=settings.LANGUAGE_COOKIE_HTTPONLY,
            samesite=settings.LANGUAGE_COOKIE_SAMESITE,
        )
        return response
    return render(request, "accounts/profile.html", {"form": form, "profile": profile_obj})


@capability_required("users.view")
def team(request):
    users = get_user_model().objects.prefetch_related("groups", "property_access__property").order_by("first_name", "username")
    invitations = Invitation.objects.filter(status=Invitation.Status.PENDING).select_related("group", "scope_property")
    return render(request, "accounts/team.html", {"users": users, "invitations": invitations})


@capability_required("users.create")
def invite(request):
    form = InvitationForm(request.POST or None)
    invitation_link = None
    if request.method == "POST" and form.is_valid():
        invitation = Invitation(email=form.cleaned_data["email"], group=form.cleaned_data["role"], scope_property=form.cleaned_data["scope_property"], invited_by=request.user, expires_at=timezone.now() + timedelta(days=7))
        raw_token = invitation.issue_token()
        invitation.save()
        invitation_link = request.build_absolute_uri(reverse("invitation_accept", args=(raw_token,)))
        send_mail("Your Oman Skylight invitation", f"Accept your invitation: {invitation_link}", None, [invitation.email], fail_silently=True)
        AuditLog.objects.create(actor=request.user, action="user.invited", target_type="accounts.Invitation", target_id=str(invitation.pk), summary=f"Invited {invitation.email}")
        messages.success(request, _("Invitation created. Copy the secure link below."))
        form = InvitationForm()
    return render(request, "accounts/invite.html", {"form": form, "invitation_link": invitation_link})


@transaction.atomic
def invitation_accept(request, token):
    invitation = Invitation.objects.filter(token=Invitation.digest(token)).select_related("group", "scope_property").first()
    if not invitation or not invitation.is_usable:
        raise Http404("Invitation is invalid or expired.")
    placeholder = get_user_model()(username=invitation.email, email=invitation.email)
    form = InvitationAcceptForm(placeholder, request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save(commit=False)
        user.username = invitation.email
        user.email = invitation.email
        user.first_name = form.cleaned_data["first_name"]
        user.last_name = form.cleaned_data["last_name"]
        user.is_staff = True
        user.save()
        user.groups.add(invitation.group)
        if invitation.scope_property:
            PropertyAccess.objects.create(user=user, property=invitation.scope_property, group=invitation.group)
        profile_obj, _created = UserProfile.objects.get_or_create(user=user)
        profile_obj.email_verified_at = timezone.now()
        profile_obj.save(update_fields=("email_verified_at", "security_updated_at"))
        invitation.status = Invitation.Status.ACCEPTED
        invitation.accepted_at = timezone.now()
        invitation.save(update_fields=("status", "accepted_at"))
        messages.success(request, _("Account activated. You can now sign in."))
        return redirect("login")
    return render(request, "accounts/invitation_accept.html", {"form": form, "invitation": invitation})


@capability_required("roles.view")
def roles(request):
    groups = Group.objects.filter(pms_profile__is_active=True).select_related("pms_profile").prefetch_related("pms_capabilities").order_by("name")
    return render(request, "accounts/roles.html", {"roles": groups})


@capability_required("roles.create")
def role_create(request):
    form = RoleForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        group = Group.objects.create(name=form.cleaned_data["name"])
        GroupProfile.objects.create(group=group, label=form.cleaned_data["label"], description=form.cleaned_data["description"], color=form.cleaned_data["color"])
        group.pms_capabilities.set(form.cleaned_data["capabilities"])
        messages.success(request, _("Role created."))
        return redirect("roles")
    return render(request, "accounts/role_form.html", {"form": form})


@capability_required("roles.update")
def role_edit(request, group_id):
    group = get_object_or_404(Group.objects.select_related("pms_profile").prefetch_related("pms_capabilities"), pk=group_id)
    if group.pms_profile.is_system:
        return HttpResponse("System roles cannot be modified.", status=403)
    initial = {"name": group.name, "label": group.pms_profile.label, "description": group.pms_profile.description, "color": group.pms_profile.color, "capabilities": group.pms_capabilities.all()}
    form = RoleForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        group.name = form.cleaned_data["name"]
        group.save(update_fields=("name",))
        profile_obj = group.pms_profile
        profile_obj.label, profile_obj.description, profile_obj.color = form.cleaned_data["label"], form.cleaned_data["description"], form.cleaned_data["color"]
        profile_obj.save()
        group.pms_capabilities.set(form.cleaned_data["capabilities"])
        messages.success(request, _("Role updated."))
        return redirect("roles")
    return render(request, "accounts/role_form.html", {"form": form, "editing": group})


@capability_required("roles.delete")
def role_delete(request, group_id):
    group = get_object_or_404(Group.objects.select_related("pms_profile"), pk=group_id)
    if request.method == "POST" and not group.pms_profile.is_system and not group.user_set.exists() and not group.property_access.exists():
        group.delete()
        messages.success(request, _("Role deleted."))
    else:
        messages.error(request, _("Assigned or system roles cannot be deleted."))
    return redirect("roles")


@capability_required("roles.clone")
def role_clone(request, group_id):
    source = get_object_or_404(Group.objects.select_related("pms_profile").prefetch_related("pms_capabilities"), pk=group_id)
    if request.method == "POST":
        base_name = f"{source.name}-copy"
        clone_name = base_name
        counter = 2
        while Group.objects.filter(name=clone_name).exists():
            clone_name = f"{base_name}-{counter}"
            counter += 1
        clone = Group.objects.create(name=clone_name)
        GroupProfile.objects.create(group=clone, label=f"{source.pms_profile.label} Copy", description=source.pms_profile.description, color=source.pms_profile.color)
        clone.pms_capabilities.set(source.pms_capabilities.all())
        messages.success(request, _("Role cloned."))
    return redirect("roles")


@capability_required("users.update")
def team_user(request, user_id):
    user = get_object_or_404(get_user_model().objects.prefetch_related("groups", "property_access"), pk=user_id)
    initial = {"first_name": user.first_name, "last_name": user.last_name, "email": user.email, "is_active": user.is_active, "roles": user.groups.all(), "properties": [item.property_id for item in user.property_access.all()]}
    form = UserManageForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid() and not user.is_superuser:
        before = {"roles": list(user.groups.values_list("name", flat=True)), "active": user.is_active}
        user.first_name, user.last_name, user.email, user.is_active = form.cleaned_data["first_name"], form.cleaned_data["last_name"], form.cleaned_data["email"], form.cleaned_data["is_active"]
        user.save(update_fields=("first_name", "last_name", "email", "is_active"))
        roles_selected = list(form.cleaned_data["roles"])
        user.groups.set(roles_selected)
        user.property_access.all().delete()
        scoped_role = roles_selected[0] if roles_selected else None
        if scoped_role:
            PropertyAccess.objects.bulk_create(PropertyAccess(user=user, property=item, group=scoped_role) for item in form.cleaned_data["properties"])
        AuditLog.objects.create(actor=request.user, action="user.updated", target_type="auth.User", target_id=str(user.pk), summary=f"Updated {user.username}", changes={"before": before, "after": {"roles": [item.name for item in roles_selected], "active": user.is_active}})
        messages.success(request, _("User access updated."))
        return redirect("team")
    return render(request, "accounts/user_form.html", {"form": form, "managed_user": user})


@capability_required("users.reset_password")
def team_user_reset_password(request, user_id):
    user = get_object_or_404(get_user_model(), pk=user_id, is_active=True)
    if request.method == "POST" and user.email:
        form = PasswordResetForm({"email": user.email})
        if form.is_valid():
            form.save(request=request, email_template_name="registration/password_reset_email.txt")
            messages.success(request, _("Password reset link sent."))
    return redirect("team_user", user_id=user.pk)


@capability_required("users.delete")
@require_POST
@transaction.atomic
def team_user_deactivate(request, user_id):
    user = get_object_or_404(get_user_model(), pk=user_id)
    if user.is_superuser or user == request.user:
        messages.error(request, _("This account cannot be deactivated here."))
        return redirect("team_user", user_id=user.pk)
    before = {"is_active": user.is_active, "roles": list(user.groups.values_list("name", flat=True))}
    user.is_active = False
    user.save(update_fields=("is_active",))
    user.groups.clear()
    user.property_access.all().delete()
    AuditLog.objects.create(actor=request.user, action="user.deactivated", target_type="auth.User", target_id=str(user.pk), summary=f"Deactivated {user.username}", changes={"before": before, "after": {"is_active": False, "roles": []}})
    messages.success(request, _("User access deactivated. Historical records were preserved."))
    return redirect("team")


@capability_required("users.resend_invitation")
def invitation_resend(request, invitation_id):
    invitation = get_object_or_404(Invitation, pk=invitation_id, status=Invitation.Status.PENDING)
    if request.method == "POST":
        raw_token = invitation.issue_token()
        invitation.expires_at = timezone.now() + timedelta(days=7)
        invitation.save(update_fields=("token", "expires_at"))
        link = request.build_absolute_uri(reverse("invitation_accept", args=(raw_token,)))
        send_mail("Your Oman Skylight invitation", f"Accept your invitation: {link}", None, [invitation.email], fail_silently=True)
        messages.success(request, _("Invitation renewed and sent."))
    return redirect("team")


@login_required
def verification_send(request):
    if request.method == "POST":
        raw_token = __import__("secrets").token_urlsafe(32)
        EmailVerificationToken.objects.create(user=request.user, token_hash=hashlib.sha256(raw_token.encode()).hexdigest(), expires_at=timezone.now() + timedelta(hours=24))
        link = request.build_absolute_uri(reverse("verification_confirm", args=(raw_token,)))
        send_mail("Verify your Oman Skylight email", f"Verify your email: {link}", None, [request.user.email], fail_silently=True)
        messages.success(request, _("Verification link sent."))
    return redirect("account_profile")


@login_required
def verification_confirm(request, token):
    record = EmailVerificationToken.objects.filter(user=request.user, token_hash=hashlib.sha256(token.encode()).hexdigest(), used_at__isnull=True).first()
    if not record or not record.is_usable:
        raise Http404("Verification link is invalid or expired.")
    record.used_at = timezone.now()
    record.save(update_fields=("used_at",))
    profile_obj = request.user.pms_profile
    profile_obj.email_verified_at = timezone.now()
    profile_obj.save(update_fields=("email_verified_at", "security_updated_at"))
    messages.success(request, _("Email address verified."))
    return redirect("account_profile")


@capability_required("roles.update")
def settings_general(request):
    form = GeneralSettingsForm(request.POST or None, initial=GeneralSettingsForm.initial_values())
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, _("Settings updated."))
        return redirect("settings_general")
    return render(request, "accounts/settings.html", {"form": form})


@login_required
def security(request):
    profile_obj, _created = UserProfile.objects.get_or_create(user=request.user)
    return render(request, "accounts/security.html", {"profile": profile_obj, "passkeys": request.user.passkeys.all(), "recovery_count": request.user.recovery_codes.filter(used_at__isnull=True).count()})


PASSWORD_CONFIRM_SESSION_KEY = "password_confirmed_at"


def _password_is_confirmed(request):
    confirmed_at = request.session.get(PASSWORD_CONFIRM_SESSION_KEY, 0)
    return bool(confirmed_at and time.time() - confirmed_at <= getattr(settings, "PASSWORD_CONFIRM_TIMEOUT", 10800))


@login_required
def password_confirmation_status(request):
    return JsonResponse({"confirmed": _password_is_confirmed(request)})


@login_required
def confirm_password(request):
    next_url = request.POST.get("next") or request.GET.get("next") or reverse("account_security")
    if not url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        next_url = reverse("account_security")
    form = PasswordConfirmationForm(request.user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        request.session[PASSWORD_CONFIRM_SESSION_KEY] = time.time()
        messages.success(request, _("Password confirmed."))
        return redirect(next_url)
    return render(request, "accounts/confirm_password.html", {"form": form, "next": next_url})


@login_required
def password_change(request):
    form = PasswordChangeForm(request.user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        update_session_auth_hash(request, user)
        request.session[PASSWORD_CONFIRM_SESSION_KEY] = time.time()
        messages.success(request, _("Password changed."))
        return redirect("account_security")
    return render(request, "accounts/password_change.html", {"form": form})


@login_required
@require_POST
@transaction.atomic
def recovery_codes_regenerate(request):
    if not _password_is_confirmed(request):
        messages.error(request, _("Confirm your password before regenerating recovery codes."))
        return redirect(f"{reverse('confirm_password')}?next={reverse('account_security')}")
    profile_obj = request.user.pms_profile
    if not profile_obj.two_factor_enabled:
        return HttpResponse(_("Two-factor authentication is not enabled."), status=400)
    raw_codes, hashes = generate_recovery_codes()
    request.user.recovery_codes.all().delete()
    RecoveryCode.objects.bulk_create(RecoveryCode(user=request.user, code_hash=item) for item in hashes)
    request.session["new_recovery_codes"] = raw_codes
    AuditLog.objects.create(actor=request.user, action="security.recovery_codes_regenerated", target_type="auth.User", target_id=str(request.user.pk), summary="Regenerated recovery codes")
    return redirect("two_factor_recovery_codes")


@login_required
@require_POST
def passkey_delete(request, passkey_id):
    if not _password_is_confirmed(request):
        messages.error(request, _("Confirm your password before deleting a passkey."))
        return redirect(f"{reverse('confirm_password')}?next={reverse('account_security')}")
    passkey = get_object_or_404(Passkey, pk=passkey_id, user=request.user)
    name = passkey.name
    passkey.delete()
    AuditLog.objects.create(actor=request.user, action="security.passkey_deleted", target_type="accounts.Passkey", target_id=str(passkey_id), summary=f"Deleted passkey {name}"[:255])
    messages.success(request, _("Passkey deleted."))
    return redirect("account_security")


@login_required
@require_POST
@transaction.atomic
def account_deactivate(request):
    form = PasswordConfirmationForm(request.user, request.POST)
    if request.user.is_superuser:
        messages.error(request, _("The primary administrator account cannot deactivate itself."))
        return redirect("account_profile")
    if not form.is_valid():
        messages.error(request, _("Password confirmation failed."))
        return redirect("account_profile")
    user = request.user
    AuditLog.objects.create(actor=user, action="user.self_deactivated", target_type="auth.User", target_id=str(user.pk), summary=f"Deactivated {user.username}", changes={"before": {"is_active": True}, "after": {"is_active": False}})
    user.is_active = False
    user.save(update_fields=("is_active",))
    logout(request)
    return redirect("login")


@login_required
def two_factor_setup(request):
    profile_obj, _created = UserProfile.objects.get_or_create(user=request.user)
    secret = request.session.get("two_factor_setup_secret") or pyotp.random_base32()
    request.session["two_factor_setup_secret"] = secret
    uri = pyotp.TOTP(secret).provisioning_uri(name=request.user.email or request.user.username, issuer_name="Oman Skylight")
    form = TwoFactorCodeForm(request.POST or None)
    if request.method == "POST" and form.is_valid() and pyotp.TOTP(secret).verify(form.cleaned_data["code"], valid_window=1):
        profile_obj.two_factor_secret = encrypt(secret)
        profile_obj.two_factor_enabled = True
        profile_obj.save(update_fields=("two_factor_secret", "two_factor_enabled", "security_updated_at"))
        raw_codes, hashes = generate_recovery_codes()
        request.user.recovery_codes.all().delete()
        RecoveryCode.objects.bulk_create(RecoveryCode(user=request.user, code_hash=item) for item in hashes)
        request.session["two_factor_verified"] = True
        request.session["new_recovery_codes"] = raw_codes
        request.session.pop("two_factor_setup_secret", None)
        return redirect("two_factor_recovery_codes")
    factory = qrcode.image.svg.SvgPathImage
    image = qrcode.make(uri, image_factory=factory)
    response = HttpResponse(content_type="image/svg+xml")
    image.save(response)
    return render(request, "accounts/two_factor_setup.html", {"form": form, "qr_svg": response.content.decode(), "secret": secret})


@login_required
def two_factor_challenge(request):
    profile_obj, _created = UserProfile.objects.get_or_create(user=request.user)
    if not profile_obj.two_factor_enabled:
        return redirect("dashboard")
    form = TwoFactorCodeForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        code = form.cleaned_data["code"].strip().replace(" ", "")
        valid = pyotp.TOTP(decrypt(profile_obj.two_factor_secret)).verify(code, valid_window=1) if code.isdigit() else consume_recovery_code(request.user, code)
        if valid:
            request.session["two_factor_verified"] = True
            return redirect(request.session.pop("two_factor_next", reverse("dashboard")))
        form.add_error("code", _("The code is invalid or has already been used."))
    return render(request, "accounts/two_factor_challenge.html", {"form": form})


@login_required
def two_factor_recovery_codes(request):
    codes = request.session.pop("new_recovery_codes", None)
    if codes is None:
        return redirect("account_security")
    return render(request, "accounts/recovery_codes.html", {"codes": codes})


@login_required
def two_factor_disable(request):
    if request.method == "POST" and request.user.check_password(request.POST.get("password", "")):
        profile_obj = request.user.pms_profile
        profile_obj.two_factor_enabled = False
        profile_obj.two_factor_secret = ""
        profile_obj.save(update_fields=("two_factor_enabled", "two_factor_secret", "security_updated_at"))
        request.user.recovery_codes.all().delete()
        request.session.pop("two_factor_verified", None)
        messages.success(request, _("Two-factor authentication disabled."))
    else:
        messages.error(request, _("Password confirmation failed."))
    return redirect("account_security")


def _encode_challenge(value):
    return base64.urlsafe_b64encode(value).decode()


def _decode_challenge(value):
    return base64.urlsafe_b64decode(value.encode())


@login_required
def passkey_registration_options(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)
    options = generate_registration_options(
        rp_id=settings.PASSKEY_RP_ID,
        rp_name="Oman Skylight",
        user_id=str(request.user.pk).encode(),
        user_name=request.user.email or request.user.username,
        user_display_name=request.user.get_full_name() or request.user.username,
        authenticator_selection=AuthenticatorSelectionCriteria(resident_key=ResidentKeyRequirement.PREFERRED, user_verification=UserVerificationRequirement.PREFERRED),
        exclude_credentials=[PublicKeyCredentialDescriptor(id=bytes(item.credential_id)) for item in request.user.passkeys.all()],
    )
    request.session["passkey_registration_challenge"] = _encode_challenge(options.challenge)
    return HttpResponse(options_to_json(options), content_type="application/json")


@login_required
def passkey_registration_verify(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)
    payload = json.loads(request.body)
    challenge = request.session.pop("passkey_registration_challenge", None)
    if not challenge:
        return JsonResponse({"error": "Registration challenge expired"}, status=400)
    try:
        verification = verify_registration_response(credential=payload["credential"], expected_challenge=_decode_challenge(challenge), expected_rp_id=settings.PASSKEY_RP_ID, expected_origin=settings.PASSKEY_ORIGIN, require_user_verification=True)
        Passkey.objects.create(user=request.user, name=payload.get("name", "Passkey")[:100], credential_id=verification.credential_id, public_key=verification.credential_public_key, sign_count=verification.sign_count)
    except Exception:
        return JsonResponse({"error": "Passkey registration could not be verified"}, status=400)
    return JsonResponse({"ok": True})


def passkey_authentication_options(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)
    payload = json.loads(request.body)
    user = get_user_model().objects.filter(username=payload.get("username", ""), is_active=True).first()
    if not user or not user.passkeys.exists():
        return JsonResponse({"error": "No passkey is registered for this account"}, status=400)
    options = generate_authentication_options(rp_id=settings.PASSKEY_RP_ID, allow_credentials=[PublicKeyCredentialDescriptor(id=bytes(item.credential_id)) for item in user.passkeys.all()], user_verification=UserVerificationRequirement.PREFERRED)
    request.session["passkey_authentication_challenge"] = _encode_challenge(options.challenge)
    request.session["passkey_authentication_user"] = user.pk
    return HttpResponse(options_to_json(options), content_type="application/json")


def passkey_authentication_verify(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)
    payload = json.loads(request.body)
    challenge = request.session.pop("passkey_authentication_challenge", None)
    user_id = request.session.pop("passkey_authentication_user", None)
    if not challenge or not user_id:
        return JsonResponse({"error": "Authentication challenge expired"}, status=400)
    user = get_object_or_404(get_user_model(), pk=user_id, is_active=True)
    try:
        passkey = user.passkeys.get(credential_id=base64url_to_bytes(payload["credential"]["id"]))
        verification = verify_authentication_response(credential=payload["credential"], expected_challenge=_decode_challenge(challenge), expected_rp_id=settings.PASSKEY_RP_ID, expected_origin=settings.PASSKEY_ORIGIN, credential_public_key=bytes(passkey.public_key), credential_current_sign_count=passkey.sign_count, require_user_verification=True)
        passkey.sign_count = verification.new_sign_count
        passkey.last_used_at = timezone.now()
        passkey.save(update_fields=("sign_count", "last_used_at"))
        auth_login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        request.session["two_factor_verified"] = True
    except Exception:
        return JsonResponse({"error": "Passkey authentication failed"}, status=400)
    return JsonResponse({"ok": True, "redirect": reverse("dashboard")})
