from django.contrib import admin

from .models import (
    Amenity,
    DepositDeduction,
    DepositSettlement,
    Lease,
    LeaseUnitHistory,
    LeaseNotificationEvent,
    Property,
    PropertyMedia,
    PropertyRate,
    PropertyType,
    RentSchedule,
    Region,
    City,
    Tenant,
    TenantDocument,
    TenantInvitation,
    Unit,
    UnitRate,
    UnitType,
    UnitTypeRate,
)

admin.site.site_header = "Oman Skylight PMS"
admin.site.site_title = "Oman Skylight PMS"
admin.site.index_title = "Property management"


class UnitInline(admin.TabularInline):
    model = Unit
    extra = 0


class PropertyMediaInline(admin.TabularInline):
    model = PropertyMedia
    extra = 0


class PropertyRateInline(admin.TabularInline):
    model = PropertyRate
    extra = 0


@admin.register(Property)
class PropertyAdmin(admin.ModelAdmin):
    list_display = ("name", "property_type", "rental_mode", "city", "is_public", "is_active", "unit_count")
    list_filter = ("is_active", "is_public", "rental_mode", "property_type", "city")
    search_fields = ("name", "address", "city")
    prepopulated_fields = {"slug": ("name",)}
    filter_horizontal = ("amenities",)
    inlines = (UnitInline, PropertyRateInline, PropertyMediaInline)

    @admin.display(description="Units")
    def unit_count(self, obj):
        return obj.units.count()


@admin.register(Unit)
class UnitAdmin(admin.ModelAdmin):
    list_display = ("name", "property", "unit_type", "bedrooms", "monthly_rent", "status")
    list_filter = ("status", "property", "unit_type", "is_furnished")
    search_fields = ("name", "property__name")


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ("full_name", "phone", "email", "portal_enabled", "is_active")
    list_filter = ("is_active", "portal_enabled", "nationality")
    search_fields = ("full_name", "phone", "email", "id_number")


@admin.register(Lease)
class LeaseAdmin(admin.ModelAdmin):
    list_display = (
        "tenant",
        "unit",
        "start_date",
        "end_date",
        "monthly_rent",
        "status",
    )
    list_filter = ("status", "unit__property")
    search_fields = ("tenant__full_name", "unit__name", "unit__property__name")
    autocomplete_fields = ("tenant", "unit")
    filter_horizontal = ("tenants",)


@admin.register(PropertyType, Region, City, Amenity, UnitType, PropertyRate, UnitTypeRate, UnitRate, TenantDocument, TenantInvitation, RentSchedule, LeaseUnitHistory, LeaseNotificationEvent, DepositSettlement, DepositDeduction)
class ReferenceAdmin(admin.ModelAdmin):
    list_display = ("__str__",)

# Register your models here.
