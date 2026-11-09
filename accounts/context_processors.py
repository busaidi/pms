from .access import user_has_capability


NAVIGATION_ROUTE_PREFIXES = {
    "properties": ("property_", "unit_", "rate_", "amenity_", "transfer_", "inventory_", "media_"),
    "tenants": ("tenant_",),
    "applications": ("application_",),
    "leases": ("lease_",),
    "invoices": ("invoice_", "manual_invoice_", "generate_invoice_", "record_invoice_"),
    "payments": ("payment_", "review_payment", "signed_invoice_payment"),
    "maintenance": ("maintenance_",),
    "expenses": ("expense_", "recurring_expense_"),
    "utilities": ("utility_",),
    "inspections": ("inspection_",),
    "portal": ("portal_",),
    "team": ("team", "invitation_"),
    "roles": ("role_", "roles"),
    "integrations": ("integration_", "mail_", "whatsapp_", "extension_"),
    "account": (
        "account_",
        "password_change",
        "confirm_password",
        "password_confirmation_",
        "two_factor_",
        "recovery_codes_",
        "passkey_",
        "verification_",
    ),
}


def active_navigation(request):
    match = request.resolver_match
    if not match:
        return ""
    if match.namespace == "admin":
        return "administration"

    route_name = match.url_name or ""
    if route_name == "dashboard":
        return "overview"
    if route_name in {"financial_dashboard", "rent_dashboard"}:
        return "financial-reports"
    if route_name in {
        "settings_general",
        "payment_gateway_settings",
        "reminder_settings",
        "run_reminders",
        "public_portal_settings",
    }:
        return "integrations"
    for section, prefixes in NAVIGATION_ROUTE_PREFIXES.items():
        if route_name.startswith(prefixes):
            return section
    return ""


def access_navigation(request):
    user = request.user
    unread_notifications = user.pms_notifications.filter(read_at__isnull=True).count() if user.is_authenticated else 0
    has_portal_identity = False
    if user.is_authenticated:
        from portal.selectors import has_portal_identity as portal_identity
        has_portal_identity = portal_identity(user)
    lease_alert_count = 0
    if user.is_authenticated:
        from properties.lease_alerts import lease_alerts_for
        lease_alert_count = lease_alerts_for(user).count()
    return {
        "lease_alert_count": lease_alert_count,
        "can_manage_users": user_has_capability(user, "users.view"),
        "can_manage_roles": user_has_capability(user, "roles.view"),
        "can_manage_settings": user_has_capability(user, "roles.update"),
        "can_view_properties": user_has_capability(user, "properties.view"),
        "can_view_tenants": user_has_capability(user, "tenants.view") or (user.is_authenticated and user.property_access.filter(group__pms_capabilities__name="tenants.view").exists()),
        "can_view_leases": user_has_capability(user, "leases.view") or (user.is_authenticated and user.property_access.filter(group__pms_capabilities__name="leases.view").exists()),
        "can_view_financials": user_has_capability(user, "financials.view") or user_has_capability(user, "leases.view") or (user.is_authenticated and user.property_access.filter(group__pms_capabilities__name="leases.view").exists()),
        "can_view_maintenance": user_has_capability(user, "maintenance-tickets.view") or (user.is_authenticated and user.property_access.filter(group__pms_capabilities__name="maintenance-tickets.view").exists()),
        "unread_notifications": unread_notifications,
        "has_portal_identity": has_portal_identity,
        "active_navigation": active_navigation(request),
    }
