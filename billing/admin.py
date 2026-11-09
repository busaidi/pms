from django.contrib import admin

from .models import Invoice, InvoiceLineItem, InvoicePdfArtifact, Payment, PaymentAllocation, PaymentAnomaly, PaymentAttempt, PaymentProof, PaymentWebhook


class InvoiceLineInline(admin.TabularInline):
    model = InvoiceLineItem
    extra = 1


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ("number", "lease", "issue_date", "due_date", "total", "status")
    list_filter = ("status", "currency", "due_date")
    search_fields = ("number", "lease__tenant__full_name")
    autocomplete_fields = ("lease",)
    inlines = (InvoiceLineInline,)


class PaymentAllocationInline(admin.TabularInline):
    model = PaymentAllocation
    extra = 0


class PaymentProofInline(admin.TabularInline):
    model = PaymentProof
    extra = 0


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("reference", "invoice", "tenant", "amount", "method", "status", "payment_date")
    list_filter = ("status", "method", "gateway")
    search_fields = ("reference", "tenant__full_name", "gateway_reference")
    autocomplete_fields = ("tenant",)
    inlines = (PaymentAllocationInline, PaymentProofInline)


@admin.register(PaymentAttempt, PaymentWebhook, PaymentAnomaly, InvoicePdfArtifact)
class PaymentEventAdmin(admin.ModelAdmin):
    list_display = ("__str__",)

# Register your models here.
