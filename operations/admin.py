from django.contrib import admin

from .models import (
    Expense, ExpenseCategory, Inspection, InspectionItem, InspectionPhoto,
    InspectionTemplate, InspectionTemplateItem, MaintenanceAttachment,
    MaintenanceTicket, RecurringExpense, ReminderLog, UtilityMeter, UtilityReading,
    MaintenanceStatusHistory, ReminderSettings, UserNotification,
)


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ("incurred_on", "property", "category", "amount", "vendor")
    list_filter = ("category", "property", "incurred_on")
    search_fields = ("description", "vendor", "property__name")


@admin.register(RecurringExpense)
class RecurringExpenseAdmin(admin.ModelAdmin):
    list_display = ("description", "property", "amount", "frequency", "next_run_on", "is_paused")
    list_filter = ("frequency", "is_paused", "property")


class MaintenanceAttachmentInline(admin.TabularInline):
    model = MaintenanceAttachment
    extra = 0


class MaintenanceHistoryInline(admin.TabularInline):
    model = MaintenanceStatusHistory
    extra = 0
    readonly_fields = ("from_status", "to_status", "notes", "actor", "created_at")


@admin.register(MaintenanceTicket)
class MaintenanceTicketAdmin(admin.ModelAdmin):
    list_display = ("title", "property", "unit", "priority", "status", "assigned_to", "created_at")
    list_filter = ("status", "priority", "property")
    search_fields = ("title", "description", "unit__name", "tenant__full_name")
    inlines = (MaintenanceAttachmentInline, MaintenanceHistoryInline)


class TemplateItemInline(admin.TabularInline):
    model = InspectionTemplateItem
    extra = 1


@admin.register(InspectionTemplate)
class InspectionTemplateAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active")
    inlines = (TemplateItemInline,)


class InspectionItemInline(admin.TabularInline):
    model = InspectionItem
    extra = 0


@admin.register(Inspection)
class InspectionAdmin(admin.ModelAdmin):
    list_display = ("unit", "template", "scheduled_for", "inspector", "status")
    list_filter = ("status", "template", "unit__property")
    inlines = (InspectionItemInline,)


@admin.register(ExpenseCategory, UtilityMeter, UtilityReading, InspectionPhoto, ReminderLog, ReminderSettings, UserNotification)
class OperationsReferenceAdmin(admin.ModelAdmin):
    list_display = ("__str__",)

# Register your models here.
