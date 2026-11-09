from django.db import migrations


def forwards(apps, schema_editor):
    Lease = apps.get_model("properties", "Lease")
    Tenant = apps.get_model("properties", "Tenant")
    DepositSettlement = apps.get_model("properties", "DepositSettlement")
    used = set(Lease.objects.exclude(reference__isnull=True).values_list("reference", flat=True))
    for lease in Lease.objects.select_related("unit").order_by("created_at", "pk"):
        prefix = f"LSX{lease.created_at.year}"
        sequence = 1
        reference = f"{prefix}{sequence:04d}"
        while reference in used:
            sequence += 1; reference = f"{prefix}{sequence:04d}"
        used.add(reference)
        lease.reference = reference
        lease.property_id = lease.unit.property_id if lease.unit_id else lease.property_id
        lease.primary_tenant_id = lease.tenant_id
        lease.rent_amount = lease.monthly_rent
        if lease.status == "ended": lease.status = "terminated"
        lease.save(update_fields=("reference", "property", "primary_tenant", "rent_amount", "status"))
        lease.tenants.add(lease.tenant_id)
    for tenant in Tenant.objects.all():
        if tenant.emergency_contact and not tenant.emergency_contact_name:
            tenant.emergency_contact_name = tenant.emergency_contact
            tenant.save(update_fields=("emergency_contact_name",))
    for settlement in DepositSettlement.objects.select_related("lease"):
        settlement.original_amount = settlement.deposit_received or settlement.lease.security_deposit
        settlement.currency = settlement.lease.currency
        if settlement.settled_at:
            settlement.status = "settled"; settlement.settlement_date = settlement.settled_at.date()
        settlement.save(update_fields=("original_amount", "currency", "status", "settlement_date"))


class Migration(migrations.Migration):
    dependencies = [("properties", "0006_depositsettlement_currency_and_more")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
