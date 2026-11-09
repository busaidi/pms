from django.contrib import admin

from .models import AppSetting, AuditLog, Capability, EmailVerificationToken, GroupProfile, Invitation, Passkey, PropertyAccess, RecoveryCode, UserProfile


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "phone", "preferred_language", "email_verified_at", "two_factor_enabled")
    search_fields = ("user__username", "user__email", "phone")


@admin.register(PropertyAccess)
class PropertyAccessAdmin(admin.ModelAdmin):
    list_display = ("user", "property", "group", "created_at")
    list_filter = ("group", "property")
    autocomplete_fields = ("user", "property", "group")


@admin.register(Invitation)
class InvitationAdmin(admin.ModelAdmin):
    list_display = ("email", "group", "scope_property", "status", "expires_at", "invited_by")
    list_filter = ("status", "group")
    search_fields = ("email",)
    readonly_fields = ("token", "created_at", "accepted_at")

    def has_add_permission(self, request):
        return False


@admin.register(Passkey)
class PasskeyAdmin(admin.ModelAdmin):
    list_display = ("name", "user", "last_used_at", "created_at")
    readonly_fields = ("credential_id", "public_key", "sign_count", "last_used_at", "created_at")


@admin.register(AppSetting)
class AppSettingAdmin(admin.ModelAdmin):
    list_display = ("key", "group", "value_type", "is_secret", "updated_at")
    list_filter = ("group", "value_type", "is_secret")
    search_fields = ("key",)


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "actor", "action", "target_type", "summary")
    list_filter = ("action", "target_type")
    search_fields = ("summary", "target_id", "actor__username")
    readonly_fields = tuple(field.name for field in AuditLog._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Capability)
class CapabilityAdmin(admin.ModelAdmin):
    list_display = ("name", "label")
    search_fields = ("name", "label", "description")
    filter_horizontal = ("groups",)


@admin.register(GroupProfile)
class GroupProfileAdmin(admin.ModelAdmin):
    list_display = ("label", "group", "is_system", "is_active", "color")
    list_filter = ("is_system", "is_active")


@admin.register(RecoveryCode, EmailVerificationToken)
class SecurityRecordAdmin(admin.ModelAdmin):
    list_display = ("__str__",)

# Register your models here.
