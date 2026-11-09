import logging
import subprocess
import base64
import hashlib

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST
from django.db import transaction

from accounts.access import properties_for_user
from .contract_forms import ContractProfileForm, ContractTermsForm, ContractTemplateSelectionForm, ContractTermsPreviewForm
from .contract_services import ensure_contract, ensure_contract_pdf, render_contract, terms_preview_contract
from .models import Lease, LeaseContract, LeaseContractProfile, ContractTermsTemplate
from .contract_terms import default_terms

logger = logging.getLogger(__name__)


def prepare_contract_pdf(request, contract):
    try:
        return ensure_contract_pdf(contract)
    except (OSError, ValueError, subprocess.SubprocessError):
        logger.warning("PDF rendering failed for lease contract %s", contract.pk)
        messages.warning(request, _("Contract saved. PDF is temporarily unavailable; preview it or retry downloading."))
        return None


def _contract(user, lease_id, contract_id):
    return get_object_or_404(LeaseContract.objects.select_related("lease").filter(
        lease__property__in=properties_for_user(user, "leases.view")), lease_id=lease_id, pk=contract_id)


def _preview_response(contract):
    response = HttpResponse(render_contract(contract))
    response["Cache-Control"] = "private, no-store"
    response["Content-Security-Policy"] = "default-src 'none'; img-src data:; font-src data:; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"
    from pathlib import Path
    from django.conf import settings
    script = (Path(settings.BASE_DIR) / "static/js/contract-pagination.js").read_text(encoding="utf-8")
    digest = base64.b64encode(hashlib.sha256(script.encode()).digest()).decode()
    response["Content-Security-Policy"] += f"; script-src 'sha256-{digest}'"
    return response


@login_required
def contract_preview(request, lease_id, contract_id):
    return _preview_response(_contract(request.user, lease_id, contract_id))


@login_required
@require_POST
def terms_template_preview(request, property_id):
    property_obj = get_object_or_404(properties_for_user(request.user, "properties.update"), pk=property_id)
    form = ContractTermsPreviewForm(request.POST)
    if not form.is_valid():
        response = render(request, "properties/terms_preview_error.html", {"form": form}, status=400)
        response["Cache-Control"] = "private, no-store"
        return response
    return _preview_response(terms_preview_contract(property_obj, form.cleaned_data["name"], form.cleaned_data["body"]))


@login_required
def contract_download(request, lease_id, contract_id):
    contract = prepare_contract_pdf(request, _contract(request.user, lease_id, contract_id))
    if contract is None:
        return redirect("lease_workspace", lease_id=lease_id)
    response = FileResponse(contract.file.open("rb"), as_attachment=True,
                            filename=f"{contract.snapshot['reference']}-v{contract.revision}.pdf", content_type="application/pdf")
    response["Cache-Control"] = "private, no-store"
    return response


@login_required
@require_POST
def contract_generate(request, lease_id):
    lease = get_object_or_404(Lease.objects.filter(property__in=properties_for_user(request.user, "leases.update")), pk=lease_id)
    if "terms_template" in request.POST:
        form = ContractTemplateSelectionForm(request.POST, lease=lease)
        if not form.is_valid():
            messages.error(request, "اختر قالب شروط متاحًا لهذا العقار.")
            return redirect("lease_workspace", lease_id=lease_id)
        lease.terms_template = form.cleaned_data["terms_template"]
        lease.save(update_fields=("terms_template", "updated_at"))
    contract = ensure_contract(lease)
    if prepare_contract_pdf(request, contract):
        messages.success(request, _("Contract generated from the current lease data."))
    return redirect("lease_workspace", lease_id=lease_id)


@login_required
def contract_profile(request, property_id):
    property_obj = get_object_or_404(properties_for_user(request.user, "properties.update"), pk=property_id)
    profile = LeaseContractProfile.objects.filter(property=property_obj).first() or LeaseContractProfile(property=property_obj)
    form = ContractProfileForm(request.POST or None, instance=profile)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, _("Contract defaults saved. Existing contract versions are unchanged."))
        return redirect("lease_list")
    return render(request, "properties/form.html", {"form": form, "title": _("Contract template settings"), "eyebrow": property_obj.name})


@login_required
def terms_template_list(request):
    properties = properties_for_user(request.user, "properties.update")
    for property_obj in properties:
        default_terms(property_obj)
    return render(request, "properties/terms_template_list.html", {
        "properties": properties,
        "templates": ContractTermsTemplate.objects.filter(property__in=properties).select_related("property"),
    })


@login_required
@transaction.atomic
def terms_template_edit(request, property_id, template_id=None):
    property_obj = get_object_or_404(properties_for_user(request.user, "properties.update"), pk=property_id)
    template = (get_object_or_404(ContractTermsTemplate.objects.select_for_update(), pk=template_id, property=property_obj)
                if template_id else ContractTermsTemplate(property=property_obj))
    initial = {}
    if not template_id:
        source_id = request.GET.get("copy")
        source = get_object_or_404(ContractTermsTemplate, pk=source_id, property=property_obj) if source_id else default_terms(property_obj)
        initial = {"body": source.body, "name": f"نسخة من {source.name}" if source_id else ""}
    form = ContractTermsForm(request.POST if request.method == "POST" else None, instance=template, initial=initial)
    if request.method == "POST" and form.is_valid():
        if template_id and form.cleaned_data["expected_revision"] != template.revision:
            form.add_error(None, "عدّل مستخدم آخر هذا القالب. افتح الصفحة مجددًا قبل حفظ تغييراتك.")
        else:
            saved = form.save(commit=False)
            saved.revision = template.revision + 1 if template_id else 1
            saved.save()
            messages.success(request, "تم حفظ قالب الشروط. النسخ السابقة من العقود محفوظة دون تغيير.")
            return redirect("terms_template_list")
    return render(request, "properties/terms_template_form.html", {"form": form, "property": property_obj, "template": template})
