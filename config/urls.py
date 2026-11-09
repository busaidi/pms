"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path
from accounts import views as account_views
from core import views as core_views
from portal import views as portal_views

urlpatterns = [
    path("i18n/setlang/", core_views.set_language_preference, name="set_language"),
    path("", include("core.urls")),
    path("properties/", include("properties.urls")),
    path("", include("properties.leasing_urls")),
    path("", include("billing.urls")),
    path("", include("operations.urls")),
    path("", include("integrations.urls")),
    path("listings/", include("portal.urls")),
    path("portal/", include("portal.self_urls")),
    path("applications/", include("portal.staff_urls")),
    path("settings/public-portal/", portal_views.public_portal_settings, name="public_portal_settings"),
    path("account/", include("accounts.urls")),
    path("team/", account_views.team, name="team"),
    path("team/invite/", account_views.invite, name="team_invite"),
    path("team/<int:user_id>/", account_views.team_user, name="team_user"),
    path("team/<int:user_id>/reset-password/", account_views.team_user_reset_password, name="team_user_reset_password"),
    path("team/<int:user_id>/deactivate/", account_views.team_user_deactivate, name="team_user_deactivate"),
    path("team/invitations/<int:invitation_id>/resend/", account_views.invitation_resend, name="invitation_resend"),
    path("invite/<str:token>/", account_views.invitation_accept, name="invitation_accept"),
    path("roles/", account_views.roles, name="roles"),
    path("roles/new/", account_views.role_create, name="role_create"),
    path("roles/<int:group_id>/edit/", account_views.role_edit, name="role_edit"),
    path("roles/<int:group_id>/delete/", account_views.role_delete, name="role_delete"),
    path("roles/<int:group_id>/clone/", account_views.role_clone, name="role_clone"),
    path("settings/", account_views.settings_general, name="settings_general"),
    path(
        "login/",
        auth_views.LoginView.as_view(template_name="registration/login.html"),
        name="login",
    ),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("passkey/options/", account_views.passkey_authentication_options, name="passkey_authentication_options"),
    path("passkey/verify/", account_views.passkey_authentication_verify, name="passkey_authentication_verify"),
    path("password-reset/", auth_views.PasswordResetView.as_view(template_name="registration/password_reset_form.html", email_template_name="registration/password_reset_email.txt", success_url="/password-reset/done/"), name="password_reset"),
    path("password-reset/done/", auth_views.PasswordResetDoneView.as_view(template_name="registration/password_reset_done.html"), name="password_reset_done"),
    path("reset/<uidb64>/<token>/", auth_views.PasswordResetConfirmView.as_view(template_name="registration/password_reset_confirm.html", success_url="/reset/done/"), name="password_reset_confirm"),
    path("reset/done/", auth_views.PasswordResetCompleteView.as_view(template_name="registration/password_reset_complete.html"), name="password_reset_complete"),
    path("admin/", admin.site.urls),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
