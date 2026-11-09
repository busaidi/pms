from django.contrib import admin

from .models import Application, ApplicationDocument, PortalNotification, SavedProperty


class ApplicationDocumentInline(admin.TabularInline):
    model = ApplicationDocument
    extra = 0


@admin.register(Application)
class ApplicationAdmin(admin.ModelAdmin):
    list_display = ("full_name", "property", "unit", "status", "submitted_at", "assigned_to")
    list_filter = ("status", "property", "submitted_at")
    search_fields = ("full_name", "email", "phone")
    inlines = (ApplicationDocumentInline,)


@admin.register(PortalNotification, SavedProperty)
class PortalReferenceAdmin(admin.ModelAdmin):
    list_display = ("__str__",)

# Register your models here.
