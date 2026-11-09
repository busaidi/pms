"""Add-only transfer of contract configuration, never operational data."""
import base64
import hashlib
import io
import json
from pathlib import Path

from PIL import Image
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import transaction

from accounts import audit
from .contract_terms import clean_terms
from .models import ContractTermsTemplate, LeaseContractProfile, Property

PROFILE_FIELDS = ("display_name", "location", "lessor_name", "lessor_phone", "lessor_email",
                  "plot_number", "building_number", "block_number", "road_number")
TERM_FIELDS = ("name", "body", "is_active", "is_default", "revision")
MAX_BUNDLE = 20 * 1024 * 1024


def signature_bytes(profile):
    if not profile or not profile.lessor_signature:
        return b""
    with profile.lessor_signature.open("rb") as stream:
        return stream.read()


def validate_signature(raw):
    if len(raw) > 5 * 1024 * 1024:
        raise ValueError("Signature exceeds 5 MB.")
    if raw:
        with Image.open(io.BytesIO(raw)) as image:
            if image.format != "PNG":
                raise ValueError("Signature must be PNG.")
            image.verify()


def export_bundle(properties):
    rows = []
    for prop in properties.order_by("pk"):
        profile = LeaseContractProfile.objects.filter(property=prop).first()
        terms = list(prop.terms_templates.order_by("pk").values(*TERM_FIELDS))
        if not profile and not terms:
            continue
        signature = signature_bytes(profile)
        validate_signature(signature)
        rows.append({"property": {"slug": prop.slug, "name": prop.name},
                     "profile": {field: getattr(profile, field) for field in PROFILE_FIELDS} if profile else None,
                     "signature": base64.b64encode(signature).decode("ascii"), "terms": terms})
    return {"format": "pms-contract-config", "version": 1, "properties": rows}


def load_bundle(path):
    path = Path(path)
    if path.stat().st_size > MAX_BUNDLE:
        raise ValueError("Bundle exceeds 20 MB.")
    raw = path.read_bytes()
    data = json.loads(raw)
    if set(data) != {"format", "version", "properties"} or data["format"] != "pms-contract-config" or data["version"] != 1:
        raise ValueError("Unsupported bundle format.")
    if not isinstance(data["properties"], list) or not data["properties"]:
        raise ValueError("Bundle has no properties.")
    return data, hashlib.sha256(raw).hexdigest()


def plan_import(data, lock=False):
    plan, seen = [], set()
    for row in data["properties"]:
        if set(row) != {"property", "profile", "signature", "terms"} or set(row["property"]) != {"slug", "name"}:
            raise ValueError("Unexpected configuration fields.")
        identity = row["property"]
        if not identity["slug"] or identity["slug"] in seen:
            raise ValueError("Missing or duplicate property slug.")
        seen.add(identity["slug"])
        query = Property.objects.select_for_update() if lock else Property.objects.all()
        prop = query.get(slug=identity["slug"], name=identity["name"], archived_at__isnull=True)
        signature = base64.b64decode(row["signature"], validate=True)
        validate_signature(signature)
        incoming = row["profile"]
        profile = LeaseContractProfile.objects.filter(property=prop).first()
        add_profile = False
        if incoming is not None:
            if set(incoming) != set(PROFILE_FIELDS) or any(not isinstance(v, str) for v in incoming.values()):
                raise ValueError("Invalid profile fields.")
            candidate = LeaseContractProfile(property=prop, **incoming)
            candidate.full_clean(exclude=["property"])
            if profile:
                if any(getattr(profile, field) != incoming[field] for field in PROFILE_FIELDS) or signature_bytes(profile) != signature:
                    raise ValueError(f"Profile conflict for {prop.slug}; existing data will not be overwritten.")
            else:
                add_profile = True
        elif signature:
            raise ValueError("Signature requires a profile.")
        new_terms, names = [], set()
        defaults = 0
        for term in row["terms"]:
            if set(term) != set(TERM_FIELDS) or type(term["revision"]) is not int or term["revision"] < 1:
                raise ValueError("Invalid terms fields or revision.")
            if type(term["is_active"]) is not bool or type(term["is_default"]) is not bool:
                raise ValueError("Invalid terms flags.")
            if term["is_default"] and not term["is_active"]:
                raise ValueError("Default terms must be active.")
            defaults += int(term["is_default"])
            if term["name"] in names or defaults > 1:
                raise ValueError("Duplicate terms names or defaults in bundle.")
            names.add(term["name"])
            if clean_terms(term["body"]) != term["body"]:
                raise ValueError("Terms contain unsupported HTML; sanitize on the source first.")
            candidate = ContractTermsTemplate(property=prop, **term)
            candidate.full_clean(validate_constraints=False)
            existing = list(prop.terms_templates.filter(name=term["name"]))
            if existing:
                if len(existing) != 1 or any(getattr(existing[0], key) != term[key] for key in TERM_FIELDS):
                    raise ValueError(f"Terms conflict for {prop.slug}: {term['name']}; nothing overwritten.")
            else:
                if term["is_default"] and prop.terms_templates.filter(is_default=True).exists():
                    raise ValueError(f"Default terms already exist for {prop.slug}.")
                new_terms.append(term)
        plan.append((prop, incoming, signature, add_profile, new_terms))
    return plan


def apply_bundle(data, actor):
    created_files = []
    token = audit.begin(actor)
    try:
        with transaction.atomic():
            plan = plan_import(data, lock=True)  # Recheck all conflicts under locks.
            for prop, incoming, signature, add_profile, terms in plan:
                if add_profile:
                    profile = LeaseContractProfile(property=prop, **incoming)
                    if signature:
                        profile.lessor_signature.save("imported-signature.png", ContentFile(signature), save=False)
                        created_files.append((profile.lessor_signature.storage, profile.lessor_signature.name))
                    profile.save()
                for term in terms:
                    ContractTermsTemplate.objects.create(property=prop, **term)
            return plan
    except Exception:
        for storage, name in created_files:
            storage.delete(name)
        raise
    finally:
        audit.end(token)
