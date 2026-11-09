from django.urls import path

from . import views

urlpatterns = [
    path("invoices/", views.invoice_list, name="invoice_list"),
    path("invoices/new/", views.manual_invoice_create, name="manual_invoice_create"),
    path("invoices/generate/", views.generate_invoice_batch, name="generate_invoice_batch"),
    path("invoices/<int:invoice_id>/", views.invoice_workspace, name="invoice_workspace"),
    path("invoices/<int:invoice_id>/payments/", views.record_invoice_payment, name="record_invoice_payment"),
    path("invoices/<int:invoice_id>/print/", views.invoice_print, name="invoice_print"),
    path("invoices/<int:invoice_id>/download/", views.invoice_pdf, name="invoice_pdf"),
    path("invoices/<int:invoice_id>/void/", views.invoice_void, name="invoice_void"),
    path("invoices/<int:invoice_id>/gateway/", views.invoice_gateway_start, name="invoice_gateway_start"),
    path("payments/", views.payment_list, name="payment_list"),
    path("payments/<int:payment_id>/review/", views.review_payment, name="review_payment"),
    path("payment-proofs/<int:proof_id>/", views.payment_proof_download, name="payment_proof_download"),
    path("payment-attempts/<int:attempt_id>/recheck/", views.payment_attempt_recheck, name="payment_attempt_recheck"),
    path("pay/invoices/<str:token>/", views.signed_invoice_payment, name="signed_invoice_payment"),
    path("webhooks/payments/<str:gateway>/", views.payment_webhook, name="payment_webhook"),
    path("api/webhooks/payment/<str:gateway>/", views.payment_webhook, name="payment_webhook_api"),
    path("settings/payment-gateway/", views.payment_gateway_settings, name="payment_gateway_settings"),
]
