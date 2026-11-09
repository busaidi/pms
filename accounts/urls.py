from django.urls import path

from . import views

urlpatterns = [
    path("profile/", views.profile, name="account_profile"),
    path("security/", views.security, name="account_security"),
    path("password/", views.password_change, name="password_change"),
    path("confirm-password/", views.confirm_password, name="confirm_password"),
    path("confirmed-password-status/", views.password_confirmation_status, name="password_confirmation_status"),
    path("deactivate/", views.account_deactivate, name="account_deactivate"),
    path("two-factor/setup/", views.two_factor_setup, name="two_factor_setup"),
    path("two-factor/challenge/", views.two_factor_challenge, name="two_factor_challenge"),
    path("two-factor/recovery-codes/", views.two_factor_recovery_codes, name="two_factor_recovery_codes"),
    path("two-factor/recovery-codes/regenerate/", views.recovery_codes_regenerate, name="recovery_codes_regenerate"),
    path("two-factor/disable/", views.two_factor_disable, name="two_factor_disable"),
    path("passkeys/register/options/", views.passkey_registration_options, name="passkey_registration_options"),
    path("passkeys/register/verify/", views.passkey_registration_verify, name="passkey_registration_verify"),
    path("passkeys/<int:passkey_id>/delete/", views.passkey_delete, name="passkey_delete"),
    path("verification/send/", views.verification_send, name="verification_send"),
    path("verification/<str:token>/", views.verification_confirm, name="verification_confirm"),
]
