from django.urls import path

from . import self_views as views


urlpatterns = [
    path("", views.dashboard, name="portal_dashboard"),
    path("applications/", views.applications, name="portal_applications"),
    path("applications/<int:application_id>/", views.application_detail, name="portal_application_detail"),
    path("applications/<int:application_id>/withdraw/", views.application_withdraw, name="portal_application_withdraw"),
    path("leases/", views.leases, name="portal_leases"),
    path("leases/<int:lease_id>/", views.lease_detail, name="portal_lease_detail"),
    path("invoices/", views.invoices, name="portal_invoices"),
    path("invoices/<int:invoice_id>/", views.invoice_detail, name="portal_invoice_detail"),
    path("invoices/<int:invoice_id>/print/", views.invoice_print, name="portal_invoice_print"),
    path("invoices/<int:invoice_id>/pdf/", views.invoice_pdf, name="portal_invoice_pdf"),
    path("invoices/<int:invoice_id>/proof/", views.payment_submit, name="portal_payment_submit"),
    path("invoices/<int:invoice_id>/checkout/", views.gateway_start, name="portal_gateway_start"),
    path("payments/", views.payments, name="portal_payments"),
    path("payment-proofs/<int:proof_id>/", views.payment_proof, name="portal_payment_proof"),
    path("maintenance/", views.maintenance, name="portal_maintenance"),
    path("maintenance/new/", views.maintenance_create, name="portal_maintenance_create"),
    path("maintenance/<int:ticket_id>/", views.maintenance_detail, name="portal_maintenance_detail"),
    path("maintenance-attachments/<int:attachment_id>/", views.maintenance_attachment, name="portal_maintenance_attachment"),
    path("notifications/", views.notifications, name="portal_notifications"),
    path("notifications/read-all/", views.notifications_read_all, name="portal_notifications_read_all"),
    path("notifications/<int:notification_id>/read/", views.notification_read, name="portal_notification_read"),
    path("profile/", views.profile, name="portal_profile"),
]
