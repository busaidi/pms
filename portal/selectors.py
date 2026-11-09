from django.db.models import Q

from billing.models import Invoice, Payment, PaymentProof
from operations.models import MaintenanceAttachment, MaintenanceTicket
from properties.models import Lease, Tenant

from .models import Application


def tenant_for_user(user):
    if not user.is_authenticated:
        return None
    return Tenant.objects.filter(user=user, portal_enabled=True, is_active=True, archived_at__isnull=True).first()


def applications_for_user(user):
    return Application.objects.filter(user=user).select_related("property", "unit", "unit_type", "converted_tenant")


def leases_for_user(user):
    tenant = tenant_for_user(user)
    if tenant is None:
        return Lease.objects.none()
    return Lease.objects.filter(Q(tenant=tenant) | Q(primary_tenant=tenant) | Q(tenants=tenant)).distinct()


def invoices_for_user(user):
    return Invoice.objects.filter(lease__in=leases_for_user(user)).distinct()


def payments_for_user(user):
    return Payment.objects.filter(invoice__in=invoices_for_user(user)).distinct()


def payment_proofs_for_user(user):
    return PaymentProof.objects.filter(payment__in=payments_for_user(user)).distinct()


def maintenance_for_user(user):
    tenant = tenant_for_user(user)
    if tenant is None:
        return MaintenanceTicket.objects.none()
    return MaintenanceTicket.objects.filter(tenant=tenant)


def maintenance_attachments_for_user(user):
    return MaintenanceAttachment.objects.filter(ticket__in=maintenance_for_user(user))


def has_portal_identity(user):
    return bool(user.is_authenticated and (tenant_for_user(user) or Application.objects.filter(user=user).exists()))
