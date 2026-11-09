from django.contrib import admin

from .models import LegacyRecordMap, MigrationRun


@admin.register(MigrationRun)
class MigrationRunAdmin(admin.ModelAdmin):
    list_display = ("source", "status", "started_at", "completed_at")
    readonly_fields = ("source", "source_fingerprint", "domains", "status", "summary", "error_message", "started_at", "completed_at")


@admin.register(LegacyRecordMap)
class LegacyRecordMapAdmin(admin.ModelAdmin):
    list_display = ("source_table", "source_id", "target_model", "target_id", "migrated_at")
    list_filter = ("source_table", "target_model")
    search_fields = ("source_id", "target_id")
    readonly_fields = ("source", "source_table", "source_id", "target_model", "target_id", "checksum", "migrated_at")
