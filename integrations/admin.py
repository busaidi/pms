from django.contrib import admin

from .models import ExtensionHook, ExtensionInstallation, Integration, IntegrationEvent


class ExtensionHookInline(admin.TabularInline):
    model = ExtensionHook
    extra = 0


@admin.register(Integration)
class IntegrationAdmin(admin.ModelAdmin):
    list_display = ("name", "kind", "provider", "is_enabled", "last_health_check_at")
    list_filter = ("kind", "is_enabled", "provider")
    inlines = (ExtensionHookInline,)


@admin.register(IntegrationEvent)
class IntegrationEventAdmin(admin.ModelAdmin):
    list_display = ("event", "integration", "status", "attempts", "created_at", "processed_at")
    list_filter = ("status", "integration")
    readonly_fields = ("payload", "error_message", "created_at", "processed_at")


@admin.register(ExtensionInstallation)
class ExtensionInstallationAdmin(admin.ModelAdmin):
    list_display = ("name", "version", "status", "is_enabled", "is_system", "discovered_at")
    list_filter = ("status", "is_enabled", "is_system")
    readonly_fields = ("slug", "version", "description", "dependencies", "status", "last_error", "discovered_at")

# Register your models here.
