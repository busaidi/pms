from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.forms import ProfileForm
from accounts.models import UserProfile
from billing.forms import GatewayForm
from billing.gateways import start_payment_attempt
from billing.services import ensure_invoice_pdf, record_payment
from operations.models import UserNotification
from operations.services import create_ticket

from .models import Application
from .selectors import (
    applications_for_user,
    has_portal_identity,
    invoices_for_user,
    leases_for_user,
    maintenance_attachments_for_user,
    maintenance_for_user,
    payment_proofs_for_user,
    payments_for_user,
    tenant_for_user,
)
from .self_forms import PortalMaintenanceForm, PortalPaymentForm
from .services import transition_application
from django.utils.translation import gettext_lazy as _


def _require_identity(user):
    if not has_portal_identity(user):
        raise PermissionDenied


def _context(user):
    return {"portal_tenant": tenant_for_user(user), "portal_application_count": applications_for_user(user).count()}


@login_required
def dashboard(request):
    _require_identity(request.user)
    applications = applications_for_user(request.user)
    leases = leases_for_user(request.user)
    invoices = invoices_for_user(request.user)
    return render(request, "portal/self/dashboard.html", {
        **_context(request.user),
        "applications": applications[:5],
        "leases": leases.select_related("property", "unit")[:5],
        "invoices": invoices.select_related("lease__property").exclude(status__in=("void", "cancelled"))[:5],
        "outstanding_total": sum((invoice.balance for invoice in invoices.exclude(status__in=("paid", "void", "cancelled"))), 0),
        "unread_count": request.user.pms_notifications.filter(read_at__isnull=True).count(),
    })


@login_required
def applications(request):
    _require_identity(request.user)
    return render(request, "portal/self/applications.html", {**_context(request.user), "applications": applications_for_user(request.user)})


@login_required
def application_detail(request, application_id):
    application = get_object_or_404(applications_for_user(request.user), pk=application_id)
    return render(request, "portal/self/application_detail.html", {**_context(request.user), "application": application})


@login_required
@require_POST
def application_withdraw(request, application_id):
    application = get_object_or_404(applications_for_user(request.user), pk=application_id)
    try:
        transition_application(application, Application.Status.WITHDRAWN, actor=request.user, applicant=True)
        messages.success(request, _("Application withdrawn."))
    except ValidationError as error:
        messages.error(request, error.messages[0])
    return redirect("portal_application_detail", application_id=application.pk)


@login_required
def leases(request):
    _require_identity(request.user)
    items = leases_for_user(request.user).select_related("property", "unit", "primary_tenant")
    return render(request, "portal/self/leases.html", {**_context(request.user), "leases": items})


@login_required
def lease_detail(request, lease_id):
    lease = get_object_or_404(leases_for_user(request.user).select_related("property", "unit", "primary_tenant").prefetch_related("rent_schedule"), pk=lease_id)
    return render(request, "portal/self/lease_detail.html", {**_context(request.user), "lease": lease})


@login_required
def invoices(request):
    _require_identity(request.user)
    items = invoices_for_user(request.user).select_related("lease__property", "lease__unit")
    return render(request, "portal/self/invoices.html", {**_context(request.user), "invoices": items})


@login_required
def invoice_detail(request, invoice_id):
    invoice = get_object_or_404(invoices_for_user(request.user).select_related("lease__property", "lease__unit").prefetch_related("line_items", "payments__proofs", "payment_attempts"), pk=invoice_id)
    return render(request, "portal/self/invoice_detail.html", {
        **_context(request.user),
        "invoice": invoice,
        "payment_form": PortalPaymentForm(initial={"amount": invoice.balance, "payment_date": timezone.localdate(), "method": "bank_transfer"}),
        "gateway_form": GatewayForm(),
    })


@login_required
def invoice_print(request, invoice_id):
    invoice = get_object_or_404(invoices_for_user(request.user).select_related("lease__property", "lease__unit", "lease__primary_tenant").prefetch_related("line_items"), pk=invoice_id)
    return render(request, "portal/self/invoice_print.html", {**_context(request.user), "invoice": invoice})


@login_required
def invoice_pdf(request, invoice_id):
    invoice = get_object_or_404(invoices_for_user(request.user), pk=invoice_id)
    artifact = ensure_invoice_pdf(invoice)
    return FileResponse(artifact.file.open("rb"), as_attachment=True, filename=f"{invoice.number}.pdf", content_type="application/pdf")


@login_required
@require_POST
def payment_submit(request, invoice_id):
    invoice = get_object_or_404(invoices_for_user(request.user), pk=invoice_id)
    form = PortalPaymentForm(request.POST, request.FILES)
    if form.is_valid():
        try:
            payment = record_payment(invoice=invoice, actor=request.user, auto_confirm=False, **form.cleaned_data)
            messages.success(request, _("Payment proof %(payment)s was submitted for review.") % {"payment": payment.reference})
        except ValidationError as error:
            messages.error(request, error.messages[0])
    else:
        messages.error(request, _("Payment proof could not be submitted: ") + " ".join(sum(form.errors.values(), [])))
    return redirect("portal_invoice_detail", invoice_id=invoice.pk)


@login_required
@require_POST
def gateway_start(request, invoice_id):
    invoice = get_object_or_404(invoices_for_user(request.user), pk=invoice_id)
    form = GatewayForm(request.POST)
    if form.is_valid():
        try:
            attempt = start_payment_attempt(invoice, gateway=form.cleaned_data["gateway"], return_url=request.build_absolute_uri(reverse("portal_invoice_detail", kwargs={"invoice_id": invoice.pk})))
            if attempt.checkout_url:
                return redirect(attempt.checkout_url)
            messages.success(request, _("Payment instructions are ready below."))
        except ValidationError as error:
            messages.error(request, error.messages[0])
    return redirect("portal_invoice_detail", invoice_id=invoice.pk)


@login_required
def payments(request):
    _require_identity(request.user)
    items = payments_for_user(request.user).select_related("invoice", "tenant").prefetch_related("proofs")
    return render(request, "portal/self/payments.html", {**_context(request.user), "payments": items})


@login_required
def payment_proof(request, proof_id):
    proof = get_object_or_404(payment_proofs_for_user(request.user), pk=proof_id)
    if not proof.file.storage.exists(proof.file.name):
        raise Http404
    return FileResponse(proof.file.open("rb"), as_attachment=True, filename=proof.original_name or proof.file.name.rsplit("/", 1)[-1])


@login_required
def maintenance(request):
    _require_identity(request.user)
    items = maintenance_for_user(request.user).select_related("property", "unit", "assigned_to")
    return render(request, "portal/self/maintenance.html", {**_context(request.user), "tickets": items})


@login_required
def maintenance_create(request):
    tenant = tenant_for_user(request.user)
    if tenant is None:
        raise PermissionDenied
    tenant_leases = leases_for_user(request.user).filter(status__in=("active", "pending", "notice"))
    form = PortalMaintenanceForm(request.POST or None, request.FILES or None, leases=tenant_leases)
    if request.method == "POST" and form.is_valid():
        values = form.cleaned_data.copy()
        lease = values.pop("lease")
        attachment = values.pop("attachment", None)
        ticket = create_ticket(actor=request.user, attachment=attachment, block_unit=False, property=lease.property, unit=lease.unit, tenant=tenant, **values)
        messages.success(request, _("Maintenance request %(ticket)s submitted.") % {"ticket": ticket.reference})
        return redirect("portal_maintenance_detail", ticket_id=ticket.pk)
    return render(request, "portal/self/maintenance_form.html", {**_context(request.user), "form": form})


@login_required
def maintenance_detail(request, ticket_id):
    ticket = get_object_or_404(maintenance_for_user(request.user).select_related("property", "unit", "assigned_to").prefetch_related("attachments", "history"), pk=ticket_id)
    return render(request, "portal/self/maintenance_detail.html", {**_context(request.user), "ticket": ticket})


@login_required
def maintenance_attachment(request, attachment_id):
    attachment = get_object_or_404(maintenance_attachments_for_user(request.user), pk=attachment_id)
    if not attachment.file.storage.exists(attachment.file.name):
        raise Http404
    return FileResponse(attachment.file.open("rb"), as_attachment=True, filename=attachment.original_name or attachment.file.name.rsplit("/", 1)[-1])


@login_required
def notifications(request):
    _require_identity(request.user)
    return render(request, "portal/self/notifications.html", {**_context(request.user), "notifications": request.user.pms_notifications.all()})


@login_required
@require_POST
def notification_read(request, notification_id):
    notification = get_object_or_404(UserNotification, pk=notification_id, recipient=request.user)
    notification.mark_read()
    return redirect("portal_notifications")


@login_required
@require_POST
def notifications_read_all(request):
    request.user.pms_notifications.filter(read_at__isnull=True).update(read_at=timezone.now())
    messages.success(request, _("All notifications marked as read."))
    return redirect("portal_notifications")


@login_required
def profile(request):
    _require_identity(request.user)
    profile_obj, _created = UserProfile.objects.get_or_create(user=request.user)
    initial = {"first_name": request.user.first_name, "last_name": request.user.last_name, "email": request.user.email, "phone": profile_obj.phone, "preferred_language": profile_obj.preferred_language, "timezone": profile_obj.timezone}
    form = ProfileForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        request.user.first_name = form.cleaned_data["first_name"]
        request.user.last_name = form.cleaned_data["last_name"]
        request.user.email = form.cleaned_data["email"]
        request.user.save(update_fields=("first_name", "last_name", "email"))
        profile_obj.phone = form.cleaned_data["phone"]
        profile_obj.preferred_language = form.cleaned_data["preferred_language"]
        profile_obj.timezone = form.cleaned_data["timezone"]
        profile_obj.save()
        messages.success(request, _("Profile updated."))
        return redirect("portal_profile")
    return render(request, "portal/self/profile.html", {**_context(request.user), "form": form})
