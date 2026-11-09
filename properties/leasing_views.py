import hashlib
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login as auth_login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import SetPasswordForm
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from accounts.access import properties_for_user, user_has_capability
from accounts.models import UserProfile
from .forms import LeaseCreateForm, LeaseEditForm, TenantDocumentForm, TenantForm
from .lease_services import create_lease, generate_rent_schedule, move_lease, move_out_lease, renew_lease, settle_deposit, terminate_lease
from .models import Lease, LeaseNotificationEvent, Tenant, TenantDocument, TenantInvitation, Unit
from django.utils.translation import gettext_lazy as _


def _tenant_queryset(user, capability="tenants.view"):
    if user_has_capability(user, capability): return Tenant.objects.all()
    properties = properties_for_user(user, capability)
    return Tenant.objects.filter(Q(leases__property__in=properties) | Q(shared_leases__property__in=properties) | Q(created_by=user)).distinct()


def _lease_queryset(user, capability="leases.view"):
    return Lease.objects.filter(property__in=properties_for_user(user, capability)).distinct()


@login_required
def tenant_list(request):
    if not (user_has_capability(request.user, "tenants.view") or properties_for_user(request.user, "tenants.view").exists()): raise PermissionDenied
    archived = request.GET.get("status") == "archived"; items = _tenant_queryset(request.user).filter(archived_at__isnull=not archived).select_related("user")
    search = request.GET.get("q", "").strip()
    if search:
        criteria = Q(full_name__icontains=search) | Q(phone__icontains=search) | Q(email__icontains=search)
        if user_has_capability(request.user, "tenants.export_sensitive"): criteria |= Q(id_number__icontains=search)
        items = items.filter(criteria)
    return render(request, "properties/tenant_list.html", {"tenants": items, "archived": archived, "search": search})


@login_required
def tenant_create(request):
    if not (user_has_capability(request.user, "tenants.create") or properties_for_user(request.user, "tenants.create").exists()): raise PermissionDenied
    form = TenantForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        tenant = form.save(commit=False); tenant.created_by = request.user; tenant.save(); messages.success(request, _("Tenant created.")); return redirect("tenant_workspace", tenant_id=tenant.pk)
    return render(request, "properties/form.html", {"form": form, "title": "Add tenant", "eyebrow": "People"})


@login_required
def tenant_workspace(request, tenant_id):
    tenant = get_object_or_404(_tenant_queryset(request.user).select_related("user"), pk=tenant_id)
    return render(request, "properties/tenant_workspace.html", {"tenant": tenant, "leases": tenant.shared_leases.select_related("property", "unit").all(), "documents": tenant.documents.all(), "document_form": TenantDocumentForm(), "can_sensitive": user_has_capability(request.user, "tenants.export_sensitive")})


@login_required
def tenant_edit(request, tenant_id):
    tenant = get_object_or_404(_tenant_queryset(request.user, "tenants.update"), pk=tenant_id); form = TenantForm(request.POST or None, instance=tenant)
    if request.method == "POST" and form.is_valid(): form.save(); messages.success(request, _("Tenant updated.")); return redirect("tenant_workspace", tenant_id=tenant.pk)
    return render(request, "properties/form.html", {"form": form, "title": f"Edit {tenant.full_name}", "eyebrow": "Tenant workspace"})


@login_required
@require_POST
def tenant_archive(request, tenant_id):
    tenant = get_object_or_404(_tenant_queryset(request.user, "tenants.delete"), pk=tenant_id)
    try: tenant.archive(); messages.success(request, _("Tenant archived."))
    except ValidationError as error: messages.error(request, error.messages[0])
    return redirect("tenant_workspace", tenant_id=tenant.pk)


@login_required
@require_POST
def tenant_restore(request, tenant_id):
    tenant = get_object_or_404(_tenant_queryset(request.user, "tenants.delete"), pk=tenant_id); tenant.restore(); messages.success(request, _("Tenant restored."))
    return redirect("tenant_workspace", tenant_id=tenant.pk)


@login_required
@require_POST
def tenant_invite(request, tenant_id):
    tenant = get_object_or_404(_tenant_queryset(request.user, "tenants.invite"), pk=tenant_id); email = request.POST.get("email", tenant.email).strip().lower()
    if not email: messages.error(request, _("An email address is required.")); return redirect("tenant_workspace", tenant_id=tenant.pk)
    invitation, raw = TenantInvitation.issue(tenant, email); link = request.build_absolute_uri(reverse("tenant_invitation_accept", kwargs={"token": raw}))
    send_mail("Your Oman Skylight tenant account", f"Create your password: {link}", settings.DEFAULT_FROM_EMAIL, [email], fail_silently=True)
    request.session["last_tenant_invitation_link"] = link; messages.success(request, _("Tenant invitation created."))
    return redirect("tenant_workspace", tenant_id=tenant.pk)


def tenant_invitation_accept(request, token):
    invitation = TenantInvitation.objects.filter(token_hash=hashlib.sha256(token.encode()).hexdigest()).select_related("tenant").first()
    if not invitation or not invitation.is_usable: raise Http404
    User = get_user_model(); user = User.objects.filter(email__iexact=invitation.email).first()
    if not user:
        base = invitation.email.split("@", 1)[0]; username = base; counter = 2
        while User.objects.filter(username=username).exists(): username = f"{base}-{counter}"; counter += 1
        user = User(username=username, email=invitation.email, first_name=invitation.tenant.full_name); user.set_unusable_password(); user.save()
    form = SetPasswordForm(user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save(); user.is_active = True; user.save(update_fields=("is_active",)); UserProfile.objects.get_or_create(user=user)
        group = Group.objects.filter(name="tenant").first() or Group.objects.filter(name="Tenant").first()
        if group: user.groups.add(group)
        invitation.tenant.user = user; invitation.tenant.email = invitation.email; invitation.tenant.portal_enabled = True; invitation.tenant.save(update_fields=("user", "email", "portal_enabled", "updated_at"))
        from django.utils import timezone
        invitation.accepted_at = timezone.now(); invitation.save(update_fields=("accepted_at",)); auth_login(request, user); messages.success(request, _("Tenant access activated. Welcome to your resident portal.")); return redirect("portal_dashboard")
    return render(request, "properties/tenant_invitation_accept.html", {"form": form, "tenant": invitation.tenant})


@login_required
@require_POST
def tenant_disable_access(request, tenant_id):
    tenant = get_object_or_404(_tenant_queryset(request.user, "tenants.update"), pk=tenant_id)
    if tenant.user: tenant.user.is_active = False; tenant.user.save(update_fields=("is_active",))
    tenant.portal_enabled = False; tenant.save(update_fields=("portal_enabled", "updated_at")); messages.success(request, _("Tenant access disabled."))
    return redirect("tenant_workspace", tenant_id=tenant.pk)


@login_required
@require_POST
def tenant_document_add(request, tenant_id):
    tenant = get_object_or_404(_tenant_queryset(request.user, "tenants.update"), pk=tenant_id); form = TenantDocumentForm(request.POST, request.FILES)
    if form.is_valid():
        document = form.save(commit=False); document.tenant = tenant; document.mime_type = document.file.content_type or "application/octet-stream"; document.size = document.file.size; document.save(); messages.success(request, _("Document uploaded."))
    else: messages.error(request, _("Document upload failed: ") + " ".join(sum(form.errors.values(), [])))
    return redirect("tenant_workspace", tenant_id=tenant.pk)


@login_required
def tenant_document_download(request, tenant_id, document_id):
    tenant = get_object_or_404(_tenant_queryset(request.user), pk=tenant_id); document = get_object_or_404(tenant.documents, pk=document_id)
    if not document.file.storage.exists(document.file.name): raise Http404
    return FileResponse(document.file.open("rb"), as_attachment=True, filename=document.file.name.rsplit("/", 1)[-1])


@login_required
@require_POST
@transaction.atomic
def tenant_document_delete(request, tenant_id, document_id):
    tenant = get_object_or_404(_tenant_queryset(request.user, "tenants.update"), pk=tenant_id)
    document = get_object_or_404(tenant.documents, pk=document_id)
    storage, name = document.file.storage, document.file.name
    document.delete()
    transaction.on_commit(lambda: storage.delete(name))
    messages.success(request, _("Document deleted."))
    return redirect("tenant_workspace", tenant_id=tenant.pk)


@login_required
def lease_list(request):
    if not (user_has_capability(request.user, "leases.view") or properties_for_user(request.user, "leases.view").exists()): raise PermissionDenied
    leases = _lease_queryset(request.user).select_related("property", "unit", "primary_tenant")
    status = request.GET.get("status"); search = request.GET.get("q", "").strip()
    if status: leases = leases.filter(status=status)
    if search: leases = leases.filter(Q(reference__icontains=search) | Q(primary_tenant__full_name__icontains=search) | Q(property__name__icontains=search))
    return render(request, "properties/lease_list.html", {"leases": leases, "status": status or "", "search": search})


@login_required
def lease_create(request):
    properties = properties_for_user(request.user, "leases.create")
    if not properties.exists() and not user_has_capability(request.user, "leases.create"): raise PermissionDenied
    form = LeaseCreateForm(request.POST or None, properties=properties, tenants=_tenant_queryset(request.user, "tenants.view"))
    if request.method == "GET" and request.GET.get("tenant"):
        selected = form.fields["tenants"].queryset.filter(pk=request.GET["tenant"]).first()
        if selected: form.fields["tenants"].initial = [selected]
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data; target = data["target_type"]
        try:
            lease = create_lease(property_obj=data["property"], tenants=data["tenants"], unit=data["unit"] if target == "unit" else None, unit_type=data["unit_type"] if target == "unit_type" else None, start_date=data["start_date"], end_date=data["end_date"], rent_amount=data["rent_amount"], currency=data["currency"], billing_interval=data["billing_interval"], billing_unit=data["billing_unit"], billing_strategy=data["billing_strategy"], billing_day=data["billing_day"], deposit_amount=data["deposit_amount"], notes=data["notes"])
            messages.success(request, _("Lease %(lease)s created.") % {"lease": lease.reference}); return redirect("lease_workspace", lease_id=lease.pk)
        except ValidationError as error: form.add_error(None, error.messages[0])
    return render(request, "properties/form.html", {"form": form, "title": "Create lease", "eyebrow": "Occupancy"})


@login_required
def lease_workspace(request, lease_id):
    lease = get_object_or_404(_lease_queryset(request.user).select_related("property", "unit", "primary_tenant", "previous_lease").prefetch_related("tenants", "rent_schedule", "unit_history", "invoices"), pk=lease_id)
    available_units = Unit.objects.filter(property__in=properties_for_user(request.user, "leases.move"), archived_at__isnull=True, status=Unit.Status.AVAILABLE).exclude(pk=lease.unit_id)
    tenant_documents = TenantDocument.objects.filter(tenant__shared_leases=lease).select_related("tenant")
    return render(request, "properties/lease_workspace.html", {"lease": lease, "available_units": available_units, "edit_form": LeaseEditForm(instance=lease), "tenant_documents": tenant_documents, "today": date.today()})


@login_required
@require_POST
@transaction.atomic
def lease_update(request, lease_id):
    lease = get_object_or_404(_lease_queryset(request.user, "leases.update"), pk=lease_id); form = LeaseEditForm(request.POST, instance=lease)
    if lease.status != Lease.Status.ACTIVE:
        messages.error(request, _("Only active leases can be updated."))
    elif form.is_valid():
        lease = form.save(); generate_rent_schedule(lease); messages.success(request, _("Lease updated and its rent schedule refreshed."))
    else: messages.error(request, _("Lease could not be updated: ") + " ".join(sum(form.errors.values(), [])))
    return redirect("lease_workspace", lease_id=lease.pk)


@login_required
@require_POST
def lease_terminate(request, lease_id):
    lease = get_object_or_404(_lease_queryset(request.user, "leases.delete"), pk=lease_id)
    try: terminate_lease(lease, end_date=date.fromisoformat(request.POST["end_date"]), reason=request.POST.get("reason", ""), notes=request.POST.get("notes", "")); messages.success(request, _("Lease terminated."))
    except (ValidationError, ValueError) as error: messages.error(request, error.messages[0] if isinstance(error, ValidationError) else "Enter a valid termination date.")
    return redirect("lease_workspace", lease_id=lease.pk)


@login_required
@require_POST
def lease_move(request, lease_id):
    lease = get_object_or_404(_lease_queryset(request.user, "leases.move"), pk=lease_id); unit = get_object_or_404(Unit, pk=request.POST.get("unit"), property__in=properties_for_user(request.user, "leases.move"))
    try: move_lease(lease, target_unit=unit, effective_date=date.fromisoformat(request.POST["effective_date"]), reason=request.POST.get("reason", ""), actor=request.user); messages.success(request, _("Lease moved to the new unit."))
    except (ValidationError, ValueError) as error: messages.error(request, error.messages[0] if isinstance(error, ValidationError) else "Enter a valid move date.")
    return redirect("lease_workspace", lease_id=lease.pk)


@login_required
@require_POST
def lease_renew(request, lease_id):
    lease = get_object_or_404(_lease_queryset(request.user, "leases.renew"), pk=lease_id)
    try:
        renewed = renew_lease(lease, end_date=date.fromisoformat(request.POST["end_date"]), rent_amount=Decimal(request.POST["rent_amount"]), confirmed_outstanding=request.POST.get("confirmed_outstanding") == "on", deposit_handling=request.POST.get("deposit_handling", "carry_forward")); messages.success(request, _("Renewed as %(lease)s.") % {"lease": renewed.reference}); return redirect("lease_workspace", lease_id=renewed.pk)
    except (ValidationError, ValueError, InvalidOperation) as error: messages.error(request, error.messages[0] if isinstance(error, ValidationError) else "Enter valid renewal terms.")
    return redirect("lease_workspace", lease_id=lease.pk)


@login_required
@require_POST
def lease_move_out(request, lease_id):
    lease = get_object_or_404(_lease_queryset(request.user, "leases.move_out"), pk=lease_id)
    try:
        settlement = None
        if request.POST.get("settle_deposit") == "on":
            deductions = []
            for line in request.POST.get("deductions", "").splitlines():
                if "|" in line: reason, amount = line.rsplit("|", 1); deductions.append((reason, Decimal(amount.strip())))
            settlement = {"refund_amount": Decimal(request.POST.get("refund_amount") or 0), "deductions": deductions, "status": "settled", "refund_reference": request.POST.get("refund_reference", "")}
        move_out_lease(lease, end_date=date.fromisoformat(request.POST["end_date"]), reason=request.POST.get("reason", "Move out"), notes=request.POST.get("notes", ""), settlement=settlement)
        messages.success(request, _("Move-out completed."))
    except (ValidationError, ValueError, InvalidOperation) as error: messages.error(request, error.messages[0] if isinstance(error, ValidationError) else "Enter valid move-out values.")
    return redirect("lease_workspace", lease_id=lease.pk)


@login_required
@require_POST
def lease_deposit_settlement(request, lease_id):
    lease = get_object_or_404(_lease_queryset(request.user, "leases.move_out"), pk=lease_id)
    try:
        deductions = []
        for line in request.POST.get("deductions", "").splitlines():
            if "|" in line:
                reason, amount = line.rsplit("|", 1); deductions.append((reason, Decimal(amount.strip())))
        settle_deposit(
            lease,
            refund_amount=Decimal(request.POST.get("refund_amount") or 0),
            deductions=deductions,
            status="settled",
            settlement_date=date.fromisoformat(request.POST.get("settlement_date") or str(date.today())),
            refund_reference=request.POST.get("refund_reference", ""),
            notes=request.POST.get("notes", ""),
        )
        messages.success(request, _("Deposit settlement completed."))
    except (ValidationError, ValueError, InvalidOperation) as error:
        messages.error(request, error.messages[0] if isinstance(error, ValidationError) else "Enter valid settlement values.")
    return redirect("lease_workspace", lease_id=lease.pk)


@login_required
def lease_expirations(request):
    properties = properties_for_user(request.user, "leases.view"); days = int(request.GET.get("days", 60)); cutoff = date.today() + timedelta(days=days)
    leases = Lease.objects.filter(property__in=properties, status=Lease.Status.ACTIVE, end_date__range=(date.today(), cutoff)).select_related("property", "primary_tenant")
    return render(request, "properties/lease_expirations.html", {"leases": leases, "days": days, "events": LeaseNotificationEvent.objects.filter(lease__in=leases)})
