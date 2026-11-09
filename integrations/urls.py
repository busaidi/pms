from django.urls import path

from . import views


urlpatterns = [
    path("settings/mail/", views.mail_settings, name="mail_settings"),
    path("settings/mail/test/", views.mail_test, name="mail_test"),
    path("settings/whatsapp/", views.whatsapp_settings, name="whatsapp_settings"),
    path("settings/whatsapp/test/", views.whatsapp_test, name="whatsapp_test"),
    path("settings/integrations/", views.integration_list, name="integration_list"),
    path("settings/integrations/new/", views.integration_edit, name="integration_create"),
    path("settings/integrations/<int:integration_id>/", views.integration_edit, name="integration_edit"),
    path("settings/integrations/<int:integration_id>/test/", views.integration_test, name="integration_test"),
    path("settings/extensions/<int:extension_id>/toggle/", views.extension_toggle, name="extension_toggle"),
    path("settings/extensions/health/", views.extension_health, name="extension_health"),
    path("extensions/reference/", views.reference_extension_probe, name="reference_extension_probe"),
]
