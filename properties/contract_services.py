"""Approved Atheer template, populated only from an immutable lease snapshot."""

import base64
import hashlib
import json
import subprocess
from datetime import timedelta
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction
from django.template.loader import render_to_string

from .models import Lease, LeaseContract, LeaseContractProfile

TEMPLATE_VERSION = "atheer-v9"


def contract_snapshot(lease):
    from .contract_terms import terms_snapshot
    profile = LeaseContractProfile.objects.filter(property_id=lease.property_id).first()
    profile_data = {field: getattr(profile, field, "") for field in (
        "display_name", "location", "lessor_name", "lessor_phone", "lessor_email",
        "plot_number", "building_number", "block_number", "road_number",
    )}
    profile_data["display_name"] = profile_data["display_name"] or lease.property.name
    profile_data["location"] = profile_data["location"] or lease.property.address
    signature = ""
    if profile and profile.lessor_signature:
        with profile.lessor_signature.open("rb") as source:
            signature = "data:image/png;base64," + base64.b64encode(source.read()).decode()
    tenants = list(lease.tenants.order_by("pk"))
    if not tenants:
        tenants = [lease.primary_tenant or lease.tenant]
    rows = list(lease.rent_schedule.exclude(status="waived").order_by("period_start", "due_date"))
    last_day = max((row.period_end for row in rows if row.period_end), default=lease.end_date)
    checkout = last_day + timedelta(days=1) if last_day else None
    total = sum((row.amount for row in rows), Decimal("0")) if rows else None
    warnings = []
    if not profile_data["lessor_name"]:
        warnings.append("بيانات المؤجر غير مكتملة؛ أكمل إعدادات النموذج قبل اعتماد العقد.")
    if not lease.end_date:
        last_day = checkout = total = None
        warnings.append("مدة العقد مفتوحة؛ يلزم تحديد المدة قبل اعتماد هذا النموذج.")
    if not rows:
        warnings.append("لا يوجد جدول إيجار؛ إجمالي قيمة الإقامة غير محدد.")
    return {
        "reference": lease.reference, "profile": profile_data,
        "unit": lease.unit.name if lease.unit else "العقار بالكامل",
        "tenants": [{"name": t.full_name, "id_number": t.id_number, "nationality": t.nationality,
                     "phone": t.phone, "email": t.email} for t in tenants],
        "start": lease.start_date.strftime("%d/%m/%Y"),
        "last_rental_day": last_day.strftime("%d/%m/%Y") if last_day else "",
        "checkout": checkout.strftime("%d/%m/%Y") if checkout else "",
        "nights": (checkout - lease.start_date).days if checkout else None,
        "rent": f"{lease.rent_amount:.3f}", "total": f"{total:.3f}" if total is not None else "",
        "deposit": f"{lease.security_deposit:.3f}", "currency": lease.currency,
        "billing_interval": lease.billing_interval, "billing_unit": lease.billing_unit,
        "schedule": [{"date": r.due_date.strftime("%d/%m/%Y"), "amount": f"{r.amount:.3f}"} for r in rows],
        "terms": lease.terms, "warnings": warnings, "lessor_signature": signature,
        "selected_terms": terms_snapshot(lease),
        # Internal notes, payment claims, tenant signatures and source-PDF layers are never copied.
    }


@transaction.atomic
def ensure_contract(lease):
    lease = Lease.objects.select_for_update(of=("self",)).select_related("property", "unit", "tenant", "primary_tenant").get(pk=lease.pk)
    snapshot = contract_snapshot(lease)
    fingerprint = hashlib.sha256(json.dumps([TEMPLATE_VERSION, snapshot], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    previous = lease.contracts.first()
    if previous and previous.fingerprint == fingerprint:
        return previous
    return LeaseContract.objects.create(lease=lease, revision=previous.revision + 1 if previous else 1,
                                        template_version=TEMPLATE_VERSION, fingerprint=fingerprint, snapshot=snapshot)


@lru_cache(maxsize=1)
def terms_pages():
    root = Path(settings.BASE_DIR) / "properties" / "contract_templates" / "atheer-short-v1"
    return ["data:image/png;base64," + base64.b64encode((root / f"page-{page:02d}.png").read_bytes()).decode()
            for page in range(4, 12)]


@lru_cache(maxsize=1)
def contract_fonts():
    root = Path(settings.BASE_DIR) / "properties" / "contract_templates" / "fonts" / "tajawal"
    return {weight: "data:font/ttf;base64," + base64.b64encode((root / filename).read_bytes()).decode()
            for weight, filename in (("regular", "Tajawal-Regular.ttf"), ("bold", "Tajawal-Bold.ttf"))}


def render_contract(contract):
    templates = {"atheer-short-v1": "atheer_short_v1.html", "atheer-short-v2": "atheer_short_v2.html", "atheer-v3": "atheer_v3.html", "atheer-v4": "atheer_v4.html", "atheer-v5": "atheer_v5.html", "atheer-v6": "atheer_v6.html", "atheer-v7": "atheer_v7.html"}
    templates["atheer-v8"] = "atheer_v8.html"
    templates["atheer-v9"] = "atheer_v9.html"
    if contract.template_version not in templates:
        raise ValueError("Unsupported contract template version")
    return render_to_string("properties/contracts/" + templates[contract.template_version], {
        "data": contract.snapshot, "revision": contract.revision,
        "contract_fonts": contract_fonts() if contract.template_version in {"atheer-v8", "atheer-v9"} else {},
        "pagination_script": (Path(settings.BASE_DIR) / "static/js/contract-pagination.js").read_text(encoding="utf-8") if contract.template_version == "atheer-v9" else "",
        "created": contract.created_at.strftime("%d/%m/%Y"),
        "terms_pages": terms_pages() if contract.template_version == "atheer-short-v1" else [],
    })


def terms_preview_contract(property_obj, name, body):
    """An unsaved illustrative contract: never borrow a tenant's personal data."""
    from types import SimpleNamespace
    from django.utils import timezone
    profile = LeaseContractProfile.objects.filter(property=property_obj).first()
    profile_data = {field: getattr(profile, field, "") for field in (
        "display_name", "location", "lessor_name", "lessor_phone", "lessor_email",
        "plot_number", "building_number", "block_number", "road_number",
    )}
    profile_data["display_name"] = profile_data["display_name"] or property_obj.name
    profile_data["location"] = profile_data["location"] or property_obj.address
    signature = ""
    if profile and profile.lessor_signature:
        with profile.lessor_signature.open("rb") as source:
            signature = "data:image/png;base64," + base64.b64encode(source.read()).decode()
    today = timezone.localdate()
    data = {
        "reference": "معاينة غير معتمدة", "profile": profile_data, "unit": "وحدة توضيحية",
        "tenants": [{"name": "مستأجر توضيحي", "id_number": "", "nationality": "", "phone": "", "email": ""}],
        "start": today.strftime("%d/%m/%Y"), "checkout": (today + timedelta(days=7)).strftime("%d/%m/%Y"),
        "last_rental_day": (today + timedelta(days=6)).strftime("%d/%m/%Y"), "nights": 7,
        "rent": "100.000", "total": "100.000", "deposit": "20.000", "currency": "OMR",
        "billing_interval": 1, "billing_unit": "week", "schedule": [], "terms": "",
        "warnings": ["معاينة للتعديلات الحالية قبل الحفظ. بيانات المستأجر والمدة والمبالغ توضيحية فقط؛ لم يُحفظ القالب أو يُنشأ عقد."],
        "lessor_signature": signature,
        "selected_terms": {"name": name or "الشروط والأحكام العامة", "html": body},
    }
    return SimpleNamespace(snapshot=data, template_version=TEMPLATE_VERSION, revision="معاينة", created_at=timezone.now())


def render_pdf(html):
    process = subprocess.run(
        [getattr(settings, "CONTRACT_NODE_EXECUTABLE", "node"), str(Path(settings.BASE_DIR) / "tools" / "render_contract.mjs")],
        input=html.encode("utf-8"), capture_output=True, timeout=75, check=True,
        creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
    )
    if not process.stdout.startswith(b"%PDF-"):
        raise ValueError("Contract renderer did not produce a PDF")
    return process.stdout


@transaction.atomic
def ensure_contract_pdf(contract):
    contract = LeaseContract.objects.select_for_update().select_related("lease").get(pk=contract.pk)
    if contract.file and contract.file.storage.exists(contract.file.name):
        return contract
    content = render_pdf(render_contract(contract))
    contract.file.save(f"{contract.snapshot['reference']}-v{contract.revision}.pdf", ContentFile(content), save=False)
    contract.save(update_fields=("file",))
    return contract
