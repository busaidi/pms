import hashlib
import json
from datetime import datetime, time
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db.models import Q
from django.utils import timezone

from accounts.models import AppSetting, AuditLog, Capability, GroupProfile, PropertyAccess
from accounts.permissions import PERMISSIONS, label_for
from billing.models import Invoice, InvoiceLineItem, Payment, PaymentAllocation, PaymentAttempt
from operations.models import Expense, ExpenseCategory, Inspection, InspectionItem, InspectionTemplate, InspectionTemplateItem, MaintenanceTicket, RecurringExpense, ReminderLog, UserNotification, UtilityMeter, UtilityReading
from portal.models import Application
from properties.models import Amenity, City, DepositDeduction, DepositSettlement, Lease, LeaseUnitHistory, Property, PropertyRate, PropertyType, Region, Tenant, Unit, UnitRate, UnitType, UnitTypeRate

from .models import LegacyRecordMap


SOURCE = "openkos"
TABLES = (
    "users", "roles", "permissions", "settings", "regions", "cities", "property_types", "properties", "amenities", "unit_types", "units", "property_rates", "unit_type_rates", "unit_rates", "tenants", "leases", "lease_unit_histories", "deposit_settlements", "deposit_deductions", "invoices", "invoice_line_items", "payments", "payment_allocations", "payment_attempts", "expense_categories", "expenses", "recurring_expenses", "utility_meters", "utility_readings", "inspection_templates", "inspection_template_items", "inspections", "inspection_items", "applications", "maintenance_tickets", "notifications", "reminder_logs", "activity_logs", "audit_logs", "media", "tenant_documents", "payment_proofs",
)


def as_json(value, default=None):
    if value is None:
        return {} if default is None else default
    if isinstance(value, (dict, list, bool, int, float)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return value


def row_checksum(row):
    return hashlib.sha256(json.dumps(row, default=str, sort_keys=True).encode()).hexdigest()


def aware(value):
    if value is None:
        return None
    if not isinstance(value, datetime):
        value = datetime.combine(value, time.min)
    return timezone.make_aware(value) if timezone.is_naive(value) else value


class SourceDatabase:
    def __init__(self, connection):
        self.connection = connection
        self.columns = {}

    def table_exists(self, table):
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name=%s)", (table,))
            return cursor.fetchone()[0]

    def rows(self, table, order="id"):
        if not self.table_exists(table):
            return []
        with self.connection.cursor() as cursor:
            cursor.execute(f'SELECT * FROM "{table}" ORDER BY "{order}"')
            columns = [item.name for item in cursor.description]
            return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]

    def count(self, table):
        if not self.table_exists(table):
            return 0
        with self.connection.cursor() as cursor:
            cursor.execute(f'SELECT count(*) FROM "{table}"')
            return cursor.fetchone()[0]

    def fingerprint(self):
        snapshot = {table: self.count(table) for table in TABLES}
        return hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest(), snapshot

    def scalar(self, sql, params=()):
        with self.connection.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchone()[0]


class OpenKosImporter:
    domains = ("identity", "settings", "inventory", "leasing", "billing", "expenses", "utilities", "inspections", "applications", "operations", "audit", "files")

    def __init__(self, source, output=None):
        self.source = source
        self.output = output or (lambda message: None)
        self.summary = {"created": {}, "reused": {}, "source_counts": {}, "differences": []}

    def _mark(self, bucket, table):
        self.summary[bucket][table] = self.summary[bucket].get(table, 0) + 1

    def mapped(self, table, source_id, model):
        mapping = LegacyRecordMap.objects.filter(source=SOURCE, source_table=table, source_id=str(source_id)).first()
        if not mapping:
            return None
        return model.objects.filter(pk=mapping.target_id).first()

    def bind(self, table, row, target):
        LegacyRecordMap.objects.update_or_create(
            source=SOURCE, source_table=table, source_id=str(row["id"]),
            defaults={"target_model": target._meta.label, "target_id": str(target.pk), "checksum": row_checksum(row)},
        )
        return target

    def import_row(self, table, row, model, finder, defaults):
        existing = self.mapped(table, row["id"], model)
        if existing:
            self._mark("reused", table)
            return existing
        target = finder()
        if target is None:
            target = model.objects.create(**defaults)
            self._mark("created", table)
        else:
            self._mark("reused", table)
        return self.bind(table, row, target)

    def target(self, table, source_id, model):
        if source_id is None:
            return None
        return self.mapped(table, source_id, model)

    def run(self, domains=None):
        requested = tuple(domains or self.domains)
        for domain in requested:
            if domain not in self.domains:
                raise ValueError(f"Unknown migration domain: {domain}")
            getattr(self, f"import_{domain}")()
        return self.summary

    def _rows(self, table, order="id"):
        rows = self.source.rows(table, order)
        self.summary["source_counts"][table] = len(rows)
        return rows

    def import_identity(self):
        User = get_user_model()
        for row in self._rows("users"):
            email = (row.get("email") or f"legacy-{row['id']}@invalid.local").lower()
            username_base = email[:150]
            username = username_base
            suffix = 2
            while User.objects.filter(username=username).exclude(email__iexact=email).exists():
                username = f"{username_base[:140]}-{suffix}"; suffix += 1
            password = row.get("password") or "!"
            if password.startswith(("$2y$", "$2a$", "$2b$")):
                password = f"laravel_bcrypt${password}"
            name = (row.get("name") or "").strip().split(" ", 1)
            user = self.import_row("users", row, User, lambda: User.objects.filter(email__iexact=email).first(), {
                "username": username, "email": email, "first_name": name[0][:150] if name else "", "last_name": name[1][:150] if len(name) > 1 else "", "password": password,
                "is_active": bool(row.get("is_active", True)), "is_staff": False,
            })
            if user.password == "" or user.password is None:
                user.password = password; user.save(update_fields=("password",))
        for row in self._rows("roles"):
            name = (row.get("name") or f"legacy-role-{row['id']}").lower()
            group = self.import_row("roles", row, Group, lambda: Group.objects.filter(name__iexact=name).first(), {"name": name})
            GroupProfile.objects.update_or_create(group=group, defaults={"label": row.get("label") or name.replace("-", " ").title(), "description": row.get("description") or "", "color": row.get("color") or "#64748b", "is_system": bool(row.get("is_system")), "is_active": bool(row.get("is_active", True))})
        for row in self._rows("permissions"):
            name = row["name"]
            self.import_row("permissions", row, Capability, lambda: Capability.objects.filter(name=name).first(), {"name": name, "label": label_for(name), "description": PERMISSIONS.get(name, "Legacy OpenKos capability.")})
        for row in self.source.rows("role_has_permissions", "role_id"):
            group = self.target("roles", row["role_id"], Group); capability = self.target("permissions", row["permission_id"], Capability)
            if group and capability: group.pms_capabilities.add(capability)
        for row in self.source.rows("model_has_roles", "model_id"):
            user = self.target("users", row["model_id"], User); group = self.target("roles", row["role_id"], Group)
            if user and group: user.groups.add(group)

    def import_settings(self):
        for row in self._rows("settings"):
            key = f"legacy.{row['key']}"
            sensitive = any(word in row["key"].lower() for word in ("password", "secret", "token", "api_key", "credential"))
            value = {"migration_required": True} if sensitive else as_json(row.get("value"), row.get("value"))
            setting = self.import_row("settings", row, AppSetting, lambda: AppSetting.objects.filter(key=key).first(), {"key": key, "group": "legacy", "value_type": AppSetting.ValueType.JSON})
            setting.set_value(value); setting.save()
            if sensitive: self.summary["differences"].append(f"settings:{row['id']} credential requires re-entry")

    def import_inventory(self):
        for row in self._rows("regions"):
            self.import_row("regions", row, Region, lambda r=row: Region.objects.filter(country_code=r.get("country_code") or "OM", name=r["name"]).first(), {"country_code": row.get("country_code") or "OM", "name": row["name"], "is_active": True})
        for row in self._rows("cities"):
            region = self.target("regions", row["region_id"], Region)
            if region: self.import_row("cities", row, City, lambda r=row, region=region: City.objects.filter(region=region, name=r["name"]).first(), {"region": region, "name": row["name"], "is_active": True})
        for row in self._rows("property_types"):
            name = row.get("label") or row.get("slug") or f"Legacy type {row['id']}"
            self.import_row("property_types", row, PropertyType, lambda name=name: PropertyType.objects.filter(name__iexact=name).first(), {"name": name, "slug": row.get("slug"), "default_rental_mode": row.get("default_rental_mode") or "unit", "is_active": bool(row.get("is_active", True)), "sort_order": row.get("sort_order") or 0})
        for row in self._rows("amenities"):
            self.import_row("amenities", row, Amenity, lambda r=row: Amenity.objects.filter(name__iexact=r["name"]).first(), {"name": row["name"], "icon": row.get("icon") or ""})
        types_by_slug = {item.slug: item for item in PropertyType.objects.all()}
        for row in self._rows("properties"):
            city = self.target("cities", row.get("city_id"), City); region = self.target("regions", row.get("region_id"), Region)
            slug = row.get("slug") or f"legacy-property-{row['id']}"
            if Property.objects.filter(slug=slug).exists() and not LegacyRecordMap.objects.filter(source=SOURCE, source_table="properties", source_id=str(row["id"])).exists(): slug = f"legacy-{row['id']}-{slug}"[:180]
            property_type = types_by_slug.get(row.get("type"))
            defaults = {"name": row["name"], "slug": slug, "public_slug": row.get("public_slug"), "property_type": property_type, "address": row.get("address") or "Address not supplied", "postal_code": row.get("postal_code") or "", "phone": row.get("phone") or "", "description": row.get("description") or "", "city": city.name if city else "Muscat", "region": region.name if region else "", "city_ref": city, "region_ref": region, "rental_mode": row.get("rental_mode") or "unit", "is_active": bool(row.get("is_active", True)) and not row.get("deleted_at"), "is_published": bool(row.get("is_published")), "is_public": bool(row.get("is_published")), "archived_at": row.get("deleted_at")}
            self.import_row("properties", row, Property, lambda r=row: Property.objects.filter(name=r["name"], address=r.get("address") or "Address not supplied").first(), defaults)
        for row in self.source.rows("amenity_property", "property_id"):
            property_obj = self.target("properties", row["property_id"], Property); amenity = self.target("amenities", row["amenity_id"], Amenity)
            if property_obj and amenity: property_obj.amenities.add(amenity)
        for row in self._rows("unit_types"):
            property_obj = self.target("properties", row["property_id"], Property)
            if not property_obj: continue
            unit_type = self.import_row("unit_types", row, UnitType, lambda r=row, p=property_obj: UnitType.objects.filter(property=p, name=r["name"]).first(), {"property": property_obj, "name": row["name"], "public_slug": row.get("public_slug"), "description": row.get("description") or "", "bedrooms": row.get("bedrooms") or 1, "bathrooms": row.get("bathrooms") or 1, "area_sqm": row.get("size_sqm"), "furnishing": row.get("furnishing") or "unfurnished", "is_active": bool(row.get("is_active", True)) and not row.get("deleted_at"), "is_published": bool(row.get("is_published")), "archived_at": row.get("deleted_at")})
        for row in self.source.rows("amenity_unit_type", "unit_type_id"):
            unit_type = self.target("unit_types", row["unit_type_id"], UnitType); amenity = self.target("amenities", row["amenity_id"], Amenity)
            if unit_type and amenity: unit_type.amenities.add(amenity)
        rate_amounts = {}
        for row in self.source.rows("unit_rates"):
            if row.get("is_active") and (row.get("billing_unit") == "month" or row.get("billing_unit") is None): rate_amounts.setdefault(row["unit_id"], row["amount"])
        for row in self._rows("units"):
            property_obj = self.target("properties", row["property_id"], Property)
            if not property_obj: continue
            unit_type = self.target("unit_types", row.get("unit_type_id"), UnitType)
            rent = rate_amounts.get(row["id"], Decimal("0"))
            self.import_row("units", row, Unit, lambda r=row, p=property_obj: Unit.objects.filter(property=p, name=r["name"]).first(), {"property": property_obj, "unit_type": unit_type, "name": row["name"], "slug": row.get("slug"), "monthly_rent": rent, "area_sqm": row.get("size_sqm"), "floor": row.get("floor") or "", "capacity": row.get("capacity") or 1, "status": row.get("status") or "available", "notes": row.get("notes") or "", "description": row.get("description") or "", "archived_at": row.get("deleted_at")})
        self._import_rates("property_rates", PropertyRate, Property, "properties", "property_id", "property")
        self._import_rates("unit_type_rates", UnitTypeRate, UnitType, "unit_types", "unit_type_id", "unit_type")
        self._import_rates("unit_rates", UnitRate, Unit, "units", "unit_id", "unit")
        User = get_user_model()
        for row in self.source.rows("property_user", "property_id"):
            user = self.target("users", row["user_id"], User); property_obj = self.target("properties", row["property_id"], Property)
            group = user.groups.first() if user else None
            if user and property_obj and group: PropertyAccess.objects.update_or_create(user=user, property=property_obj, defaults={"group": group})

    def _import_rates(self, table, model, parent_model, parent_table, parent_id, parent_field):
        for row in self._rows(table):
            parent = self.target(parent_table, row[parent_id], parent_model)
            if not parent: continue
            starts = row.get("effective_from") or timezone.localdate()
            fields = {parent_field: parent, "amount": row["amount"], "currency": row.get("currency") or "OMR", "billing_interval": row.get("billing_interval") or 1, "billing_unit": row.get("billing_unit") or "month", "is_active": bool(row.get("is_active", True)), "starts_on": starts, "ends_on": row.get("effective_until")}
            self.import_row(table, row, model, lambda model=model, fields=fields: model.objects.filter(**{parent_field: parent, "billing_interval": fields["billing_interval"], "billing_unit": fields["billing_unit"], "currency": fields["currency"], "starts_on": starts}).first(), fields)

    def import_leasing(self):
        User = get_user_model()
        for row in self._rows("tenants"):
            user = self.target("users", row.get("user_id"), User)
            tenant = self.import_row("tenants", row, Tenant, lambda r=row: Tenant.objects.filter(id_number=r.get("id_card_number") or "").first() if r.get("id_card_number") else None, {"user": user, "full_name": row.get("name") or f"Legacy tenant {row['id']}", "email": user.email if user else "", "phone": row.get("phone") or "", "id_number": row.get("id_card_number") or "", "emergency_contact_name": row.get("emergency_contact_name") or "", "emergency_contact_phone": row.get("emergency_contact_phone") or "", "notes": row.get("notes") or "", "portal_enabled": bool(user), "is_active": bool(row.get("is_active", True)) and not row.get("deleted_at"), "archived_at": row.get("deleted_at")})
        lease_tenants = {}
        for pivot in self.source.rows("lease_tenant", "lease_id"):
            lease_tenants.setdefault(pivot["lease_id"], []).append(pivot)
        for row in self._rows("leases"):
            unit = self.target("units", row.get("unit_id"), Unit); property_obj = self.target("properties", row.get("property_id"), Property) or (unit.property if unit else None)
            primary_id = row.get("primary_tenant_id") or next((item["tenant_id"] for item in lease_tenants.get(row["id"], []) if item.get("is_primary")), None) or next((item["tenant_id"] for item in lease_tenants.get(row["id"], [])), None)
            tenant = self.target("tenants", primary_id, Tenant)
            if not tenant or not property_obj: self.summary["differences"].append(f"leases:{row['id']} skipped: missing tenant/property"); continue
            reference = row.get("reference") or f"LEGACY-LSX-{row['id']}"
            if Lease.objects.filter(reference=reference).exists() and not LegacyRecordMap.objects.filter(source=SOURCE, source_table="leases", source_id=str(row["id"])).exists(): reference = f"LEGACY-{row['id']}-{reference}"[:32]
            lease = self.import_row("leases", row, Lease, lambda reference=reference: Lease.objects.filter(reference=reference).first(), {"reference": reference, "property": property_obj, "unit": unit, "tenant": tenant, "primary_tenant": tenant, "start_date": row["start_date"], "end_date": row.get("end_date"), "rent_amount": row.get("rent_amount") or 0, "monthly_rent": row.get("rent_amount") or 0, "currency": row.get("currency") or "OMR", "billing_interval": row.get("billing_interval") or 1, "billing_unit": row.get("billing_unit") or "month", "billing_strategy": row.get("billing_strategy") or "advance", "is_custom_price": bool(row.get("is_custom_price")), "unit_rate": self.target("unit_rates", row.get("unit_rate_id"), UnitRate), "unit_type_rate": self.target("unit_type_rates", row.get("unit_type_rate_id"), UnitTypeRate), "property_rate": self.target("property_rates", row.get("property_rate_id"), PropertyRate), "security_deposit": row.get("deposit_amount") or 0, "deposit_paid_at": aware(row.get("deposit_paid_at")), "deposit_refund_amount": row.get("deposit_refund_amount"), "deposit_refunded_at": aware(row.get("deposit_refunded_at")), "billing_day": min(max(row.get("rent_due_day") or 1, 1), 28), "notes": row.get("notes") or "", "termination_date": row.get("termination_date"), "termination_reason": row.get("termination_reason") or "", "archived_at": row.get("deleted_at"), "status": row.get("status") or "active"})
            for pivot in lease_tenants.get(row["id"], []):
                member = self.target("tenants", pivot["tenant_id"], Tenant)
                if member: lease.tenants.add(member)
        for row in self.source.rows("leases"):
            lease = self.target("leases", row["id"], Lease); previous = self.target("leases", row.get("previous_lease_id"), Lease)
            if lease and previous and not lease.previous_lease_id: lease.previous_lease = previous; lease.save(update_fields=("previous_lease",))
        self._simple_leasing_history()

    def _simple_leasing_history(self):
        User = get_user_model()
        for row in self._rows("lease_unit_histories"):
            lease = self.target("leases", row["lease_id"], Lease); to_unit = self.target("units", row.get("to_unit_id"), Unit)
            if lease and to_unit: self.import_row("lease_unit_histories", row, LeaseUnitHistory, lambda: None, {"lease": lease, "unit": to_unit, "from_unit": self.target("units", row.get("from_unit_id"), Unit), "to_unit": to_unit, "moved_in_at": row.get("effective_date") or lease.start_date, "effective_date": row.get("effective_date"), "reason": row.get("reason") or "", "notes": row.get("notes") or "", "transferred_by": self.target("users", row.get("transferred_by"), User)})
        for row in self._rows("deposit_settlements"):
            lease = self.target("leases", row["lease_id"], Lease)
            if lease: self.import_row("deposit_settlements", row, DepositSettlement, lambda lease=lease: DepositSettlement.objects.filter(lease=lease).first(), {"lease": lease, "original_amount": row.get("original_amount") or 0, "deposit_received": row.get("original_amount") or 0, "currency": row.get("currency") or "OMR", "status": row.get("status") or "draft", "settlement_date": row.get("settlement_date"), "refund_amount": row.get("refund_amount") or 0, "refund_reference": row.get("refund_reference") or "", "notes": row.get("notes") or ""})
        for row in self._rows("deposit_deductions"):
            settlement = self.target("deposit_settlements", row["deposit_settlement_id"], DepositSettlement)
            if settlement: self.import_row("deposit_deductions", row, DepositDeduction, lambda: None, {"settlement": settlement, "description": row.get("description") or row.get("reason") or "Deduction", "amount": row.get("amount") or 0})

    def import_billing(self):
        User = get_user_model()
        for row in self._rows("invoices"):
            lease = self.target("leases", row["lease_id"], Lease)
            if not lease: continue
            number = row.get("reference") or f"LEGACY-INV-{row['id']}"
            if Invoice.objects.filter(number=number).exists() and not LegacyRecordMap.objects.filter(source=SOURCE, source_table="invoices", source_id=str(row["id"])).exists(): number = f"LEGACY-{row['id']}-{number}"[:40]
            issue_date = row.get("created_at").date() if row.get("created_at") else row["due_date"]
            self.import_row("invoices", row, Invoice, lambda number=number: Invoice.objects.filter(number=number).first(), {"number": number, "lease": lease, "period_start": row.get("period_start"), "period_end": row.get("period_end"), "issue_date": issue_date, "due_date": row["due_date"], "currency": row.get("currency") or "OMR", "subtotal": row.get("total") or 0, "total": row.get("total") or 0, "amount_paid": row.get("amount_paid") or 0, "status": row.get("status") or "pending"})
        for row in self._rows("invoice_line_items"):
            invoice = self.target("invoices", row["invoice_id"], Invoice)
            if invoice: self.import_row("invoice_line_items", row, InvoiceLineItem, lambda: None, {"invoice": invoice, "type": row.get("type") if row.get("type") in {"rent", "utility", "manual"} else "manual", "description": row.get("description") or "Legacy charge", "quantity": 1, "unit_price": row.get("amount") or 0, "total": row.get("amount") or 0})
        for row in self._rows("payments"):
            invoice = self.target("invoices", row.get("invoice_id"), Invoice)
            tenant = (invoice.lease.primary_tenant or invoice.lease.tenant) if invoice else None
            if not tenant: continue
            reference = row.get("reference_number") or f"LEGACY-PAY-{row['id']}"
            if Payment.objects.filter(reference=reference).exists() and not LegacyRecordMap.objects.filter(source=SOURCE, source_table="payments", source_id=str(row["id"])).exists(): reference = f"LEGACY-{row['id']}-{reference}"[:80]
            status = {"completed": "confirmed", "failed": "cancelled"}.get(row.get("status"), row.get("status") or "pending")
            self.import_row("payments", row, Payment, lambda reference=reference: Payment.objects.filter(reference=reference).first(), {"reference": reference, "invoice": invoice, "tenant": tenant, "amount": row.get("amount") or 0, "currency": row.get("currency") or (invoice.currency if invoice else "OMR"), "method": row.get("payment_method") or "other", "status": status, "payment_date": row.get("payment_date") or timezone.localdate(), "recorded_by": self.target("users", row.get("recorded_by"), User), "confirmed_by": self.target("users", row.get("confirmed_by"), User), "verified_by": self.target("users", row.get("verified_by"), User), "verified_at": aware(row.get("verified_at")), "notes": row.get("notes") or ""})
        for row in self._rows("payment_allocations"):
            payment = self.target("payments", row["payment_id"], Payment); invoice = self.target("invoices", row["invoice_id"], Invoice)
            if payment and invoice: self.import_row("payment_allocations", row, PaymentAllocation, lambda payment=payment, invoice=invoice: PaymentAllocation.objects.filter(payment=payment, invoice=invoice).first(), {"payment": payment, "invoice": invoice, "amount": row.get("amount") or 0})
        for row in self._rows("payment_attempts"):
            invoice = self.target("invoices", row.get("invoice_id"), Invoice); payment = self.target("payments", row.get("payment_id"), Payment)
            key = row.get("reference") or f"legacy-attempt-{row['id']}"
            self.import_row("payment_attempts", row, PaymentAttempt, lambda key=key: PaymentAttempt.objects.filter(idempotency_key=key).first(), {"invoice": invoice, "payment": payment, "gateway": row.get("gateway_key") or "legacy", "external_id": row.get("provider_reference") or "", "idempotency_key": key, "status": row.get("status") or "pending", "amount": row.get("amount") or 0, "currency": row.get("currency") or "OMR", "checkout_instructions": as_json(row.get("checkout_instructions"), {}), "metadata": as_json(row.get("metadata"), {}), "expires_at": row.get("expires_at"), "settled_at": row.get("settled_at"), "failed_at": row.get("failed_at"), "expired_at": row.get("expired_at"), "canceled_at": row.get("canceled_at")})

    def import_expenses(self):
        User = get_user_model(); fallback_actor = User.objects.filter(is_superuser=True).first() or User.objects.first()
        for row in self._rows("expense_categories"):
            name = row.get("label") or row.get("slug") or f"Legacy category {row['id']}"
            self.import_row("expense_categories", row, ExpenseCategory, lambda name=name: ExpenseCategory.objects.filter(name__iexact=name).first(), {"name": name, "slug": row.get("slug"), "sort_order": row.get("sort_order") or 0, "is_active": bool(row.get("is_active", True))})
        for row in self._rows("recurring_expenses"):
            property_obj = self.target("properties", row["property_id"], Property); category = self.target("expense_categories", row["expense_category_id"], ExpenseCategory)
            if property_obj and category: self.import_row("recurring_expenses", row, RecurringExpense, lambda: None, {"property": property_obj, "category": category, "amount": row["amount"], "currency": row.get("currency") or "OMR", "vendor": row.get("vendor") or "", "description": row.get("description") or "Legacy recurring expense", "billing_interval": row.get("billing_interval") or 1, "billing_unit": row.get("billing_unit") or "month", "start_date": row["start_date"], "ends_on": row.get("end_date"), "is_active": bool(row.get("is_active", True)), "next_run_on": row.get("next_due_on"), "is_paused": bool(row.get("paused_at")), "paused_at": row.get("paused_at"), "created_by": fallback_actor})
        for row in self._rows("expenses"):
            property_obj = self.target("properties", row["property_id"], Property); category = self.target("expense_categories", row["expense_category_id"], ExpenseCategory)
            if property_obj and category and fallback_actor: self.import_row("expenses", row, Expense, lambda: None, {"property": property_obj, "category": category, "recurring_expense": self.target("recurring_expenses", row.get("recurring_expense_id"), RecurringExpense), "amount": row["amount"], "currency": row.get("currency") or "OMR", "incurred_on": row["expense_date"], "vendor": row.get("vendor") or "", "description": row.get("description") or "Legacy expense", "notes": row.get("notes") or "", "reference": row.get("reference") or "", "status": row.get("status") or "active", "created_by": fallback_actor, "voided_at": row.get("voided_at"), "voided_by": self.target("users", row.get("voided_by"), User), "void_reason": row.get("void_reason") or ""})

    def import_utilities(self):
        User = get_user_model()
        for row in self._rows("utility_meters"):
            unit = self.target("units", row["unit_id"], Unit)
            if unit: self.import_row("utility_meters", row, UtilityMeter, lambda: None, {"unit": unit, "kind": row.get("utility_type") or "other", "serial_number": row.get("identifier") or f"legacy-{row['id']}", "utility_name": row.get("utility_name") or "", "unit_of_measure": row.get("measurement_unit") or "unit", "rate": row.get("rate") or 0, "currency": row.get("currency") or "OMR", "is_active": bool(row.get("is_active", True))})
        for row in self._rows("utility_readings"):
            meter = self.target("utility_meters", row["utility_meter_id"], UtilityMeter)
            if meter:
                actor = User.objects.filter(is_superuser=True).first() or User.objects.first()
                current = row.get("current_reading") or 0; previous = row.get("previous_reading"); consumption = row.get("consumption") or 0; rate = row.get("rate") or meter.rate
                read_at = timezone.make_aware(datetime.combine(row["reading_date"], time.min))
                self.import_row("utility_readings", row, UtilityReading, lambda: None, {"meter": meter, "read_at": read_at, "value": current, "previous_value": previous, "rate": rate, "charge": Decimal(str(consumption)) * Decimal(str(rate)), "recorded_by": actor, "reading_kind": row.get("reading_kind") or "reading", "reading_date": row["reading_date"], "period_start": row.get("period_start"), "period_end": row.get("period_end"), "current_reading": current, "consumption": consumption, "adjustment_consumption": row.get("adjustment_consumption") or 0, "currency": row.get("currency") or meter.currency, "reference": row.get("reference") or f"LEGACY-UTL-{row['id']}"})

    def import_inspections(self):
        User = get_user_model()
        for row in self._rows("inspection_templates"):
            self.import_row("inspection_templates", row, InspectionTemplate, lambda r=row: InspectionTemplate.objects.filter(name=r["name"]).first(), {"name": row["name"], "inspection_type": row.get("inspection_type") or "periodic", "is_active": bool(row.get("is_active", True))})
        for row in self._rows("inspection_template_items"):
            template = self.target("inspection_templates", row["inspection_template_id"], InspectionTemplate)
            if template: self.import_row("inspection_template_items", row, InspectionTemplateItem, lambda: None, {"template": template, "label": row["label"], "guidance": row.get("description") or "", "sort_order": row.get("position") or 0})
        for row in self._rows("inspections"):
            template = self.target("inspection_templates", row.get("inspection_template_id"), InspectionTemplate); property_obj = self.target("properties", row["property_id"], Property)
            inspector = self.target("users", row.get("inspector_id"), User) or User.objects.filter(is_superuser=True).first() or User.objects.first()
            if property_obj and template and inspector:
                scheduled_for = timezone.make_aware(datetime.combine(row["inspection_date"], time(hour=9)))
                self.import_row("inspections", row, Inspection, lambda: None, {"template": template, "template_name": row.get("template_name") or template.name, "property": property_obj, "unit": self.target("units", row.get("unit_id"), Unit), "lease": self.target("leases", row.get("lease_id"), Lease), "inspection_type": row.get("inspection_type") or "periodic", "inspection_date": row["inspection_date"], "scheduled_for": scheduled_for, "status": row.get("status") or "draft", "notes": row.get("notes") or "", "damage_observations": row.get("damage_observations") or "", "inspector": inspector, "completed_by": self.target("users", row.get("completed_by"), User), "completed_at": row.get("completed_at")})
        for row in self._rows("inspection_items"):
            inspection = self.target("inspections", row["inspection_id"], Inspection)
            if inspection: self.import_row("inspection_items", row, InspectionItem, lambda: None, {"inspection": inspection, "label": row["label"], "description": row.get("description") or "", "sort_order": row.get("position") or 0, "condition": row.get("condition") or "not_inspected", "notes": row.get("notes") or ""})

    def import_applications(self):
        User = get_user_model()
        for row in self._rows("applications"):
            property_obj = self.target("properties", row["property_id"], Property); unit_type = self.target("unit_types", row.get("unit_type_id"), UnitType)
            if not property_obj: continue
            target_type = "unit_type" if unit_type else "whole_property"
            self.import_row("applications", row, Application, lambda: None, {"user": self.target("users", row.get("user_id"), User), "property": property_obj, "unit_type": unit_type, "target_type": target_type, "full_name": row.get("applicant_name") or "Legacy applicant", "email": row.get("applicant_email") or "unknown@invalid.local", "phone": row.get("applicant_phone") or "", "desired_move_in": row.get("intended_move_in_date"), "intended_move_in_timeframe": row.get("intended_move_in_timeframe") or "", "message": row.get("applicant_message") or "", "operator_notes": row.get("operator_notes") or "", "applicant_feedback": row.get("applicant_feedback") or "", "open_application_key": row.get("open_application_key"), "status": {"approved": "accepted", "submitted": "new"}.get(row.get("status"), row.get("status") or "new"), "reviewed_by": self.target("users", row.get("reviewed_by"), User), "reviewed_at": row.get("reviewed_at"), "converted_tenant": self.target("tenants", row.get("converted_tenant_id"), Tenant), "converted_at": row.get("converted_at"), "rental_billing_unit": row.get("rental_billing_unit") or "", "rental_billing_interval": row.get("rental_billing_interval"), "rental_currency": row.get("rental_currency") or "", "rental_amount": row.get("rental_amount")})

    def import_operations(self):
        User = get_user_model()
        for row in self._rows("maintenance_tickets"):
            property_obj = self.target("properties", row.get("property_id"), Property); unit = self.target("units", row.get("unit_id"), Unit)
            property_obj = property_obj or (unit.property if unit else None)
            if property_obj: self.import_row("maintenance_tickets", row, MaintenanceTicket, lambda r=row: MaintenanceTicket.objects.filter(reference=r.get("reference")).first() if r.get("reference") else None, {"property": property_obj, "unit": unit, "reference": row.get("reference"), "location": row.get("location") or "", "title": row["title"], "description": row.get("description") or "", "status": row.get("status") or "reported", "priority": row.get("priority") or "medium", "assigned_to": self.target("users", row.get("assigned_to"), User), "created_by": self.target("users", row.get("created_by"), User), "cost": row.get("cost"), "actual_cost": row.get("cost"), "resolved_at": aware(row.get("resolved_at")), "resolution_notes": row.get("resolution_notes") or ""})
        for row in self._rows("notifications"):
            if str(row.get("notifiable_type", "")).endswith("Tenant"):
                tenant = self.target("tenants", row.get("notifiable_id"), Tenant)
                user = tenant.user if tenant else None
                if tenant and user is None:
                    username = f"legacy-notify-tenant-{row['notifiable_id']}"
                    user = User.objects.filter(username=username).first() or User.objects.create(username=username, is_active=False)
                    if not user.has_usable_password():
                        pass
                    else:
                        user.set_unusable_password(); user.save(update_fields=("password",))
                    tenant.user = user; tenant.save(update_fields=("user", "updated_at"))
            else:
                user = self.target("users", row.get("notifiable_id"), User)
            data = as_json(row.get("data"), {})
            if user: self.import_row("notifications", row, UserNotification, lambda: None, {"recipient": user, "kind": (row.get("type") or "legacy").split("\\")[-1][:80], "title": data.get("title") or data.get("subject") or "OpenKos notification", "message": data.get("message") or data.get("body") or json.dumps(data, default=str), "url": data.get("url") or "", "payload": data if isinstance(data, dict) else {"value": data}, "read_at": aware(row.get("read_at"))})
        for row in self._rows("reminder_logs"):
            lease = self.target("leases", row.get("lease_id"), Lease); tenant = (lease.primary_tenant or lease.tenant) if lease else None
            dedupe = f"legacy:reminder:{row['id']}"
            self.import_row("reminder_logs", row, ReminderLog, lambda dedupe=dedupe: ReminderLog.objects.filter(dedupe_key=dedupe).first(), {"kind": row.get("reminder_type") or "legacy", "recipient": tenant.email or tenant.phone if tenant else "legacy", "channel": row.get("channel") or "database", "subject_type": "properties.Lease", "subject_id": str(lease.pk) if lease else "", "status": "sent" if row.get("sent_at") else "queued", "reminder_date": row.get("scheduled_for") or timezone.localdate(), "overdue_days": row.get("overdue_days") or -1, "dedupe_key": dedupe, "sent_at": aware(row.get("sent_at")), "payload": {"legacy_notification_class": row.get("notification_class")}})

    def import_audit(self):
        User = get_user_model()
        for table in ("activity_logs", "audit_logs"):
            for row in self._rows(table):
                actor_id = row.get("actor_id")
                actor = self.target("users", actor_id, User)
                action = row.get("event") or row.get("operation") or "legacy"
                target_type = row.get("subject_type") or row.get("auditable_type") or ""
                target_id = row.get("subject_id") or row.get("auditable_id") or ""
                changes = {"before": as_json(row.get("before"), {}), "after": as_json(row.get("after"), {}), "metadata": as_json(row.get("metadata"), {})}
                self.import_row(table, row, AuditLog, lambda table=table, row=row: AuditLog.objects.filter(action=f"{table}.{action}"[:80], target_id=str(row["id"]), target_type="legacy.migration").first(), {"actor": actor, "action": f"{table}.{action}"[:80], "target_type": "legacy.migration", "target_id": str(row["id"]), "summary": f"{action} {target_type} {target_id}"[:255], "changes": changes})

    def import_files(self):
        # File metadata tables are mapped by the command's checksum/copy stage.
        # The current production source has no media, tenant documents, or proofs.
        for table in ("media", "tenant_documents", "payment_proofs"):
            rows = self._rows(table)
            if rows:
                self.summary["differences"].append(f"{table}: {len(rows)} file row(s) require the checksum copy stage")

    def reconciliation(self):
        result = {}
        for table in TABLES:
            source_count = self.source.count(table)
            mapped = LegacyRecordMap.objects.filter(source=SOURCE, source_table=table).count()
            result[table] = {"source": source_count, "mapped": mapped, "difference": source_count - mapped}
        return result
