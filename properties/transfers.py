import csv
import io
from datetime import date
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q

from .models import City, Property, PropertyType, Region, Tenant, Unit, UnitRate
from django.utils.translation import gettext_lazy as _


DATASETS = {
    "property-types": {
        "headers": ["slug", "label", "default_rental_mode", "is_active", "sort_order"],
        "permission": "properties",
    },
    "properties": {
        "headers": ["slug", "name", "type", "rental_mode", "region_country_code", "region_name", "city_name", "address", "postal_code", "phone", "description", "is_active"],
        "permission": "properties",
    },
    "units": {
        "headers": ["property_slug", "name", "slug", "unit_type", "floor", "description", "size_sqm", "capacity", "furnishing", "status", "monthly_rent"],
        "permission": "units",
    },
    "unit-rates": {
        "headers": ["property_slug", "unit_name", "billing_interval", "billing_unit", "amount", "currency", "is_active", "effective_from", "effective_until"],
        "permission": "unit-rates",
    },
    "tenants": {
        "headers": ["full_name", "phone", "email", "id_number", "nationality", "emergency_contact_name", "emergency_contact_phone", "notes", "is_active"],
        "permission": "tenants",
    },
}


TRUE_VALUES = {"1", "true", "yes"}
FALSE_VALUES = {"0", "false", "no"}


def csv_response_rows(dataset, rows):
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=DATASETS[dataset]["headers"], lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def template_csv(dataset):
    examples = {
        "property-types": {"slug": "apartment", "label": "Apartment", "default_rental_mode": "unit", "is_active": "1", "sort_order": "10"},
        "properties": {"slug": "example-residence", "name": "Example Residence", "type": "apartment", "rental_mode": "unit", "region_country_code": "OM", "region_name": "Muscat", "city_name": "Muscat", "address": "Example address", "postal_code": "100", "phone": "+968 0000 0000", "description": "", "is_active": "1"},
        "units": {"property_slug": "example-residence", "name": "101", "slug": "101", "unit_type": "One bedroom", "floor": "1", "description": "", "size_sqm": "75", "capacity": "2", "furnishing": "furnished", "status": "available", "monthly_rent": "350.000"},
        "unit-rates": {"property_slug": "example-residence", "unit_name": "101", "billing_interval": "1", "billing_unit": "month", "amount": "350.000", "currency": "OMR", "is_active": "1", "effective_from": date.today().isoformat(), "effective_until": ""},
        "tenants": {"full_name": "Example Tenant", "phone": "+968 9000 0000", "email": "tenant@example.test", "id_number": "", "nationality": "Omani", "emergency_contact_name": "", "emergency_contact_phone": "", "notes": "", "is_active": "1"},
    }
    return csv_response_rows(dataset, [examples[dataset]])


def parse_csv(upload, dataset):
    if upload.size > 2 * 1024 * 1024:
        return [], [{"line": None, "field": "file", "message": "CSV files may not exceed 2 MB."}]
    try:
        text = upload.read().decode("utf-8-sig")
    except UnicodeDecodeError:
        return [], [{"line": None, "field": "file", "message": "The CSV must be UTF-8 encoded."}]
    try:
        reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
        actual = reader.fieldnames or []
        expected = DATASETS[dataset]["headers"]
        errors = []
        missing = [header for header in expected if header not in actual]
        extra = [header for header in actual if header not in expected]
        if missing:
            errors.append({"line": 1, "field": "headers", "message": f"Missing headers: {', '.join(missing)}."})
        if extra:
            errors.append({"line": 1, "field": "headers", "message": f"Unsupported headers: {', '.join(extra)}."})
        if errors:
            return [], errors
        rows = [{key: (value or "").strip() for key, value in row.items()} for row in reader]
    except csv.Error as error:
        return [], [{"line": None, "field": "file", "message": f"Malformed CSV: {error}."}]
    if len(rows) > 1000:
        return [], [{"line": None, "field": "file", "message": "A single import may contain at most 1,000 rows."}]
    if not rows:
        return [], [{"line": None, "field": "file", "message": "The CSV contains no data rows."}]
    return rows, []


def boolean(value, field, errors, line, default=True):
    if not value:
        return default
    normalized = value.lower()
    if normalized in TRUE_VALUES:
        return True
    if normalized in FALSE_VALUES:
        return False
    errors.append({"line": line, "field": field, "message": "Use true, false, 1, or 0."})
    return default


def validate_rows(dataset, rows, user, persist=False):
    from accounts.access import properties_for_user
    errors, prepared, seen = [], [], set()
    for index, row in enumerate(rows, 2):
        before = len(errors)
        item = None
        try:
            if dataset == "property-types":
                slug, label = row["slug"], row["label"]
                if not slug or not label:
                    raise ValidationError(_("Slug and label are required."))
                key = slug.lower()
                if key in seen or PropertyType.objects.filter(slug=slug).exists():
                    raise ValidationError(_("A property type with this slug already exists."))
                seen.add(key)
                mode = row["default_rental_mode"] or "unit"
                if mode not in Property.RentalMode.values:
                    raise ValidationError(_("Rental mode must be unit, whole_property, or hybrid."))
                item = {"slug": slug, "name": label, "default_rental_mode": mode, "is_active": boolean(row["is_active"], "is_active", errors, index), "sort_order": int(row["sort_order"] or 0)}
            elif dataset == "properties":
                if not row["slug"] or not row["name"]:
                    raise ValidationError(_("Slug and name are required."))
                key = row["slug"].lower()
                if key in seen or Property.objects.filter(slug=row["slug"]).exists():
                    raise ValidationError(_("A property with this slug already exists."))
                seen.add(key)
                mode = row["rental_mode"] or "unit"
                if mode not in Property.RentalMode.values:
                    raise ValidationError(_("Rental mode must be unit, whole_property, or hybrid."))
                ptype = PropertyType.objects.filter(slug=row["type"], is_active=True).first() if row["type"] else None
                if row["type"] and not ptype:
                    raise ValidationError(_("The property type was not found or is inactive."))
                item = {**row, "property_type_id": ptype.pk if ptype else None, "rental_mode": mode, "is_active": boolean(row["is_active"], "is_active", errors, index)}
            elif dataset == "units":
                prop = Property.objects.filter(slug=row["property_slug"], archived_at__isnull=True).first()
                if not prop:
                    raise ValidationError(_("The property was not found or is archived."))
                if user is not None and not properties_for_user(user, "units.import").filter(pk=prop.pk).exists():
                    raise ValidationError(_("You do not have import access to this property."))
                if not prop.supports_unit_inventory:
                    raise ValidationError(_("This property rental mode does not support units."))
                if not row["name"]:
                    raise ValidationError(_("Unit name is required."))
                key = (prop.pk, row["name"].lower())
                if key in seen or Unit.objects.filter(property=prop, name=row["name"]).exists():
                    raise ValidationError(_("A unit with this name already exists at the property."))
                seen.add(key)
                unit_type = prop.unit_types.filter(name=row["unit_type"], archived_at__isnull=True).first() if row["unit_type"] else None
                if row["unit_type"] and not unit_type:
                    raise ValidationError(_("The unit type was not found at this property."))
                status = row["status"] or "available"
                furnishing = row["furnishing"] or "unfurnished"
                if status not in Unit.Status.values or furnishing not in Unit.Furnishing.values:
                    raise ValidationError(_("Status or furnishing value is invalid."))
                item = {**row, "property_id": prop.pk, "unit_type_id": unit_type.pk if unit_type else None, "capacity": int(row["capacity"] or 1), "monthly_rent": Decimal(row["monthly_rent"] or "0"), "area_sqm": Decimal(row["size_sqm"]) if row["size_sqm"] else None, "status": status, "furnishing": furnishing}
            elif dataset == "unit-rates":
                prop = Property.objects.filter(slug=row["property_slug"], archived_at__isnull=True).first()
                if prop and user is not None and not properties_for_user(user, "unit-rates.import").filter(pk=prop.pk).exists():
                    raise ValidationError(_("You do not have rate import access to this property."))
                unit = Unit.objects.filter(property=prop, name=row["unit_name"], archived_at__isnull=True).first() if prop else None
                if not unit:
                    raise ValidationError(_("The referenced unit could not be resolved."))
                interval = int(row["billing_interval"])
                billing_unit = row["billing_unit"]
                currency = row["currency"].upper()
                starts_on = date.fromisoformat(row["effective_from"])
                ends_on = date.fromisoformat(row["effective_until"]) if row["effective_until"] else None
                key = (unit.pk, interval, billing_unit, currency, starts_on)
                if key in seen or UnitRate.objects.filter(unit=unit, billing_interval=interval, billing_unit=billing_unit, currency=currency, starts_on=starts_on).exists():
                    raise ValidationError(_("A rate with this period, currency, and start date already exists."))
                seen.add(key)
                item = {"unit_id": unit.pk, "billing_interval": interval, "billing_unit": billing_unit, "amount": Decimal(row["amount"]), "currency": currency, "is_active": boolean(row["is_active"], "is_active", errors, index), "starts_on": starts_on, "ends_on": ends_on}
                candidate = UnitRate(**item)
                candidate.full_clean(exclude=("unit",))
            else:
                if not row["full_name"] or not row["phone"]: raise ValidationError(_("Full name and phone are required."))
                key = (row["id_number"] or f"{row['full_name'].lower()}|{row['phone']}")
                if key in seen or (row["id_number"] and Tenant.objects.filter(id_number=row["id_number"]).exists()): raise ValidationError(_("This tenant already exists."))
                seen.add(key)
                item = {**row, "is_active": boolean(row["is_active"], "is_active", errors, index)}
        except (ValidationError, ValueError, InvalidOperation) as error:
            message = error.messages[0] if isinstance(error, ValidationError) else "One or more values have an invalid format."
            errors.append({"line": index, "field": "row", "message": message})
        if len(errors) == before and item:
            prepared.append(item)
    if errors or not persist:
        return prepared, errors
    with transaction.atomic():
        for item in prepared:
            if dataset == "property-types":
                PropertyType.objects.create(**item)
            elif dataset == "properties":
                region = None
                city = None
                if item["region_name"]:
                    region, _created = Region.objects.get_or_create(country_code=(item["region_country_code"] or "OM").upper(), name=item["region_name"])
                if region and item["city_name"]:
                    city, _created = City.objects.get_or_create(region=region, name=item["city_name"])
                Property.objects.create(slug=item["slug"], name=item["name"], property_type_id=item["property_type_id"], rental_mode=item["rental_mode"], region=item["region_name"], city=item["city_name"] or "Muscat", region_ref=region, city_ref=city, address=item["address"], postal_code=item["postal_code"], phone=item["phone"], description=item["description"], is_active=item["is_active"])
            elif dataset == "units":
                Unit.objects.create(property_id=item["property_id"], unit_type_id=item["unit_type_id"], name=item["name"], slug=item["slug"] or None, floor=item["floor"], description=item["description"], area_sqm=item["area_sqm"], capacity=item["capacity"], furnishing=item["furnishing"], status=item["status"], monthly_rent=item["monthly_rent"])
            elif dataset == "unit-rates":
                UnitRate.objects.create(**item)
            else:
                Tenant.objects.create(**item)
    return prepared, []


def export_rows(dataset, properties, sensitive=False):
    if dataset == "property-types":
        return [{"slug": obj.slug, "label": obj.name, "default_rental_mode": obj.default_rental_mode, "is_active": int(obj.is_active), "sort_order": obj.sort_order} for obj in PropertyType.objects.all()]
    if dataset == "properties":
        return [{"slug": obj.slug, "name": obj.name, "type": obj.property_type.slug if obj.property_type else "", "rental_mode": obj.rental_mode, "region_country_code": obj.region_ref.country_code if obj.region_ref else "OM", "region_name": obj.region_ref.name if obj.region_ref else obj.region, "city_name": obj.city_ref.name if obj.city_ref else obj.city, "address": obj.address, "postal_code": obj.postal_code, "phone": obj.phone, "description": obj.description, "is_active": int(obj.is_active)} for obj in properties.select_related("property_type", "region_ref", "city_ref")]
    units = Unit.objects.filter(property__in=properties).select_related("property", "unit_type")
    if dataset == "units":
        return [{"property_slug": obj.property.slug, "name": obj.name, "slug": obj.slug, "unit_type": obj.unit_type.name if obj.unit_type else "", "floor": obj.floor, "description": obj.description, "size_sqm": obj.area_sqm or "", "capacity": obj.capacity, "furnishing": obj.furnishing, "status": obj.status, "monthly_rent": obj.monthly_rent} for obj in units]
    if dataset == "unit-rates":
        return [{"property_slug": obj.unit.property.slug, "unit_name": obj.unit.name, "billing_interval": obj.billing_interval, "billing_unit": obj.billing_unit, "amount": obj.amount, "currency": obj.currency, "is_active": int(obj.is_active), "effective_from": obj.starts_on, "effective_until": obj.ends_on or ""} for obj in UnitRate.objects.filter(unit__in=units).select_related("unit", "unit__property")]
    tenants = Tenant.objects.filter(archived_at__isnull=True)
    if properties.count() != Property.objects.count(): tenants = tenants.filter(Q(leases__property__in=properties) | Q(shared_leases__property__in=properties)).distinct()
    return [{"full_name": obj.full_name, "phone": obj.phone, "email": obj.email, "id_number": obj.id_number if sensitive else "", "nationality": obj.nationality, "emergency_contact_name": obj.emergency_contact_name, "emergency_contact_phone": obj.emergency_contact_phone, "notes": obj.notes, "is_active": int(obj.is_active)} for obj in tenants]
