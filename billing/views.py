from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import FileResponse, Http404, JsonResponse
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from accounts.access import properties_for_user, user_has_capability
from properties.models import Lease

from .forms import GatewayForm, GatewaySettingsForm, ManualInvoiceForm, PaymentForm, PaymentReviewForm
from .gateways import process_webhook, reconcile_attempt, start_payment_attempt
from .models import Invoice, Payment, PaymentAttempt, PaymentProof
from .services import create_manual_invoice, ensure_invoice_pdf, generate_invoices, invoice_from_signed_token, record_payment, signed_invoice_token, verify_payment, void_invoice
from integrations.models import Integration
from django.utils.translation import gettext_lazy as _


def _invoice_queryset(user, capability="leases.view"):
    if user_has_capability(user, "financials.view") or user_has_capability(user, capability):
        return Invoice.objects.all()
    properties = properties_for_user(user, capability)
    if capability != "leases.view" and not properties.exists():
        properties = properties_for_user(user, "leases.view")
    return Invoice.objects.filter(lease__property__in=properties).distinct()


def _lease_queryset(user, capability="payments.create"):
    if user_has_capability(user, capability): return Lease.objects.all()
    return Lease.objects.filter(property__in=properties_for_user(user, capability)).distinct()


def _require_billing_view(user):
    if not (user_has_capability(user, "financials.view") or user_has_capability(user, "leases.view") or properties_for_user(user, "leases.view").exists()): raise PermissionDenied


@login_required
def invoice_list(request):
    _require_billing_view(request.user)
    invoices = _invoice_queryset(request.user).select_related("lease__property", "lease__unit", "lease__primary_tenant")
    status = request.GET.get("status", ""); search = request.GET.get("q", "").strip(); lease_id = request.GET.get("lease")
    if status: invoices = invoices.filter(status=status)
    if lease_id: invoices = invoices.filter(lease_id=lease_id)
    if search: invoices = invoices.filter(number__icontains=search)
    page = Paginator(invoices, 25).get_page(request.GET.get("page"))
    can_create = user_has_capability(request.user, "payments.create") or properties_for_user(request.user, "payments.create").exists()
    return render(request, "billing/invoice_list.html", {"invoices": page, "status": status, "search": search, "can_create": can_create})


@login_required
def invoice_workspace(request, invoice_id):
    _require_billing_view(request.user)
    invoice = get_object_or_404(_invoice_queryset(request.user).select_related("lease__property", "lease__unit", "lease__primary_tenant").prefetch_related("line_items", "payments__proofs", "payment_attempts"), pk=invoice_id)
    signed_url = request.build_absolute_uri(reverse("signed_invoice_payment", kwargs={"token": signed_invoice_token(invoice)}))
    return render(request, "billing/invoice_workspace.html", {
        "invoice": invoice, "payment_form": PaymentForm(initial={"amount": invoice.balance, "payment_date": timezone.localdate()}),
        "review_form": PaymentReviewForm(), "gateway_form": GatewayForm(), "signed_url": signed_url,
        "can_record": user_has_capability(request.user, "payments.create") or properties_for_user(request.user, "payments.create").filter(pk=invoice.lease.property_id).exists(),
        "can_verify": user_has_capability(request.user, "payments.verify") or properties_for_user(request.user, "payments.verify").filter(pk=invoice.lease.property_id).exists(),
        "can_send_reminders": user_has_capability(request.user, "reminders.send"),
    })


@login_required
@require_POST
def generate_invoice_batch(request):
    leases = _lease_queryset(request.user, "payments.create").filter(status=Lease.Status.ACTIVE)
    if not leases.exists() and not user_has_capability(request.user, "payments.create"): raise PermissionDenied
    if request.POST.get("lease"): leases = leases.filter(pk=request.POST["lease"])
    count = sum(len(generate_invoices(lease)) for lease in leases)
    messages.success(request, _("Generated %(count)s new invoices.") % {"count": count})
    return redirect("invoice_list")


@login_required
def manual_invoice_create(request):
    leases = _lease_queryset(request.user, "payments.create")
    if not leases.exists() and not user_has_capability(request.user, "payments.create"): raise PermissionDenied
    form = ManualInvoiceForm(request.POST or None, leases=leases.select_related("property", "unit"))
    if request.method == "POST" and form.is_valid():
        try:
            invoice = create_manual_invoice(actor=request.user, **form.cleaned_data)
            messages.success(request, _("Invoice %(invoice)s created.") % {"invoice": invoice.number}); return redirect("invoice_workspace", invoice_id=invoice.pk)
        except ValidationError as error: form.add_error(None, error.messages[0])
    return render(request, "properties/form.html", {"form": form, "title": "Create manual invoice", "eyebrow": "Billing"})


@login_required
@require_POST
def record_invoice_payment(request, invoice_id):
    invoice = get_object_or_404(_invoice_queryset(request.user, "payments.create"), pk=invoice_id)
    form = PaymentForm(request.POST, request.FILES)
    if form.is_valid():
        try:
            proof = form.cleaned_data["proof"]
            payment = record_payment(invoice=invoice, actor=request.user, auto_confirm=not proof or user_has_capability(request.user, "payments.verify"), **form.cleaned_data)
            messages.success(request, _("Payment %(payment)s recorded as %(status)s.") % {"payment": payment.reference, "status": payment.get_status_display().lower()})
        except ValidationError as error: messages.error(request, error.messages[0])
    else: messages.error(request, _("Payment could not be recorded: ") + " ".join(sum(form.errors.values(), [])))
    return redirect("invoice_workspace", invoice_id=invoice.pk)


@login_required
@require_POST
def review_payment(request, payment_id):
    payment = get_object_or_404(Payment.objects.select_related("invoice__lease__property"), pk=payment_id)
    invoice = get_object_or_404(_invoice_queryset(request.user, "payments.verify"), pk=payment.invoice_id)
    form = PaymentReviewForm(request.POST)
    if form.is_valid():
        try: verify_payment(payment, confirmed=form.cleaned_data["decision"] == "confirm", actor=request.user, notes=form.cleaned_data["notes"]); messages.success(request, _("Payment review saved."))
        except ValidationError as error: messages.error(request, error.messages[0])
    return redirect("invoice_workspace", invoice_id=invoice.pk)


@login_required
def payment_list(request):
    _require_billing_view(request.user)
    payments = Payment.objects.filter(invoice__in=_invoice_queryset(request.user)).select_related("invoice", "tenant", "recorded_by", "verified_by")
    status = request.GET.get("status", "")
    if status: payments = payments.filter(status=status)
    return render(request, "billing/payment_list.html", {"payments": Paginator(payments, 25).get_page(request.GET.get("page")), "status": status})


@login_required
def payment_proof_download(request, proof_id):
    proof = get_object_or_404(PaymentProof.objects.select_related("payment__invoice"), pk=proof_id)
    get_object_or_404(_invoice_queryset(request.user), pk=proof.payment.invoice_id)
    if not proof.file.storage.exists(proof.file.name): raise Http404
    return FileResponse(proof.file.open("rb"), as_attachment=True, filename=proof.original_name or proof.file.name.rsplit("/", 1)[-1])


@login_required
def invoice_print(request, invoice_id):
    invoice = get_object_or_404(_invoice_queryset(request.user).select_related("lease__property", "lease__unit", "lease__primary_tenant").prefetch_related("line_items"), pk=invoice_id)
    return render(request, "billing/invoice_print.html", {"invoice": invoice})


@login_required
def invoice_pdf(request, invoice_id):
    invoice = get_object_or_404(_invoice_queryset(request.user), pk=invoice_id); artifact = ensure_invoice_pdf(invoice)
    return FileResponse(artifact.file.open("rb"), as_attachment=True, filename=f"{invoice.number}.pdf", content_type="application/pdf")


@login_required
@require_POST
def invoice_void(request, invoice_id):
    invoice = get_object_or_404(_invoice_queryset(request.user, "payments.verify"), pk=invoice_id)
    try: void_invoice(invoice, actor=request.user, reason=request.POST.get("reason", "")); messages.success(request, _("Invoice voided."))
    except ValidationError as error: messages.error(request, error.messages[0])
    return redirect("invoice_workspace", invoice_id=invoice.pk)


@login_required
@require_POST
def invoice_gateway_start(request, invoice_id):
    invoice = get_object_or_404(_invoice_queryset(request.user, "payments.create"), pk=invoice_id); form = GatewayForm(request.POST)
    if form.is_valid():
        try:
            attempt = start_payment_attempt(invoice, gateway=form.cleaned_data["gateway"], return_url=request.build_absolute_uri(reverse("invoice_workspace", kwargs={"invoice_id": invoice.pk})))
            messages.success(request, _("Payment attempt %(attempt)s started.") % {"attempt": attempt.idempotency_key})
        except ValidationError as error: messages.error(request, error.messages[0])
    return redirect("invoice_workspace", invoice_id=invoice.pk)


@login_required
@require_POST
def payment_attempt_recheck(request, attempt_id):
    attempt = get_object_or_404(PaymentAttempt.objects.select_related("invoice"), pk=attempt_id)
    get_object_or_404(_invoice_queryset(request.user, "payments.verify"), pk=attempt.invoice_id)
    reconcile_attempt(attempt); messages.success(request, _("Payment attempt rechecked."))
    return redirect("invoice_workspace", invoice_id=attempt.invoice_id)


def signed_invoice_payment(request, token):
    try: invoice = invoice_from_signed_token(token)
    except (signing.BadSignature, signing.SignatureExpired, Invoice.DoesNotExist): raise Http404
    form = GatewayForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            attempt = start_payment_attempt(invoice, gateway=form.cleaned_data["gateway"], return_url=request.build_absolute_uri())
            return render(request, "billing/signed_payment.html", {"invoice": invoice, "form": form, "attempt": attempt})
        except ValidationError as error: form.add_error(None, error.messages[0])
    return render(request, "billing/signed_payment.html", {"invoice": invoice, "form": form})


@csrf_exempt
@require_POST
def payment_webhook(request, gateway):
    attempt = process_webhook(gateway, request.body, request.headers.get("X-Payment-Signature", ""))
    return JsonResponse({"received": True, "attempt": attempt.pk if attempt else None})


@login_required
def payment_gateway_settings(request):
    if not user_has_capability(request.user, "roles.update"): raise PermissionDenied
    integration = Integration.objects.filter(kind=Integration.Kind.PAYMENT, provider="manual").first()
    config = integration.configuration if integration else {}
    initial = {"is_enabled": integration.is_enabled if integration else True, "secret_reference": integration.secret_reference if integration else "PAYMENT_WEBHOOK_SECRET", **config}
    form = GatewaySettingsForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        values = form.cleaned_data
        if not values["is_enabled"] and PaymentAttempt.objects.filter(gateway="manual", status=PaymentAttempt.Status.PENDING).exists():
            form.add_error("is_enabled", _("Resolve pending payment attempts before disabling this gateway."))
            return render(request, "properties/form.html", {"form": form, "title": "Payment gateway", "eyebrow": "Settings"})
        Integration.objects.update_or_create(
            name="Manual bank transfer",
            defaults={"kind": Integration.Kind.PAYMENT, "provider": "manual", "is_enabled": values["is_enabled"], "secret_reference": values["secret_reference"], "configuration": {key: values[key] for key in ("bank_name", "account_name", "iban", "instructions")}},
        )
        messages.success(request, _("Payment gateway settings saved.")); return redirect("payment_gateway_settings")
    return render(request, "properties/form.html", {"form": form, "title": "Payment gateway", "eyebrow": "Settings"})
