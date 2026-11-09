from .registry import ExtensionManifest, register_manifest


class ReferenceNotificationDriver:
    label = "Reference log notification"

    def send(self, recipient, subject, message):
        return {"recipient": recipient, "subject": subject, "status": "logged"}


class ReferencePaymentGateway:
    label = "Reference sandbox payment"

    def health(self):
        return {"status": "ok", "mode": "sandbox"}


def _listener(event, payload):
    return {"event": event, "received": True, "payload": payload}


def register(context):
    context.add("navigation", "reference-status", {"label": "Extension status", "url_name": "integration_list"}, 90)
    context.add("dashboards", "reference-panel", {"title": "Extension platform", "template": "integrations/reference_panel.html"})
    context.add("workspaces", "reference-tab", {"label": "Extension data", "template": "integrations/reference_tab.html"})
    context.add("settings", "reference-settings", {"label": "Reference extension", "url_name": "reference_extension_probe"})
    context.add("permissions", "reference-extension.view", {"label": "View reference extension", "description": "Access the extension lifecycle probe."})
    context.add("notification_drivers", "reference-log", ReferenceNotificationDriver())
    context.add("payment_gateways", "reference-sandbox", ReferencePaymentGateway())
    context.add("routes", "reference-probe", {"path": "extensions/reference/", "url_name": "reference_extension_probe"})
    context.add("migrations", "reference-schema", "integrations.0002_extensioninstallation")
    context.add("event_listeners", "reference-events", ("reference.ping", _listener))


register_manifest(ExtensionManifest(
    slug="reference-extension",
    name="Reference extension",
    version="1.0.0",
    description="Exercises every Django extension registry and lifecycle point.",
    register=register,
    is_system=True,
))
