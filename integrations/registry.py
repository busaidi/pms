from dataclasses import dataclass, field
from importlib import import_module
from importlib.util import find_spec
import logging

from django.apps import apps
from django.utils.translation import gettext_lazy as _


logger = logging.getLogger(__name__)
PLATFORM_VERSION = "1.0.0"


def _version(value):
    try:
        return tuple(int(part) for part in value.split(".")[:3])
    except (TypeError, ValueError):
        return (0, 0, 0)


@dataclass(frozen=True)
class RegistryItem:
    extension: str
    key: str
    value: object
    order: int = 100


class SlotRegistry:
    def __init__(self, name):
        self.name = name
        self._items = {}

    def register(self, extension, key, value, order=100):
        composite = (extension, key)
        if composite in self._items:
            raise ValueError(
                _("%(registry)s item %(item)s is already registered")
                % {"registry": self.name, "item": f"{extension}:{key}"}
            )
        self._items[composite] = RegistryItem(extension, key, value, order)

    def all(self):
        return sorted(self._items.values(), key=lambda item: (item.order, item.extension, item.key))

    def get(self, extension, key):
        return self._items[(extension, key)].value

    def clear(self):
        self._items.clear()


class RegistryCollection:
    slot_names = ("navigation", "dashboards", "workspaces", "settings", "permissions", "notification_drivers", "payment_gateways", "routes", "migrations", "event_listeners")

    def __init__(self):
        for name in self.slot_names:
            setattr(self, name, SlotRegistry(name))

    def clear(self):
        for name in self.slot_names:
            getattr(self, name).clear()

    def counts(self):
        return {name: len(getattr(self, name).all()) for name in self.slot_names}


registries = RegistryCollection()


@dataclass(frozen=True)
class ExtensionManifest:
    slug: str
    name: str
    version: str
    register: object
    description: str = ""
    dependencies: dict = field(default_factory=dict)
    minimum_platform_version: str = "1.0.0"
    order: int = 100
    is_system: bool = False


class ExtensionContext:
    def __init__(self, slug):
        self.slug = slug

    def add(self, slot, key, value, order=100):
        getattr(registries, slot).register(self.slug, key, value, order)


_manifests = {}
_states = {}


def register_manifest(manifest):
    if manifest.slug in _manifests and _manifests[manifest.slug] != manifest:
        raise ValueError(
            _("Extension %(extension)s is already registered")
            % {"extension": manifest.slug}
        )
    _manifests[manifest.slug] = manifest


def unregister_manifest(slug):
    _manifests.pop(slug, None)


def _ordered_manifests():
    result, visiting, visited = [], set(), set()

    def visit(manifest):
        if manifest.slug in visited:
            return
        if manifest.slug in visiting:
            raise ValueError(
                _("Circular extension dependency at %(extension)s")
                % {"extension": manifest.slug}
            )
        visiting.add(manifest.slug)
        for dependency in manifest.dependencies:
            if dependency in _manifests:
                visit(_manifests[dependency])
        visiting.remove(manifest.slug)
        visited.add(manifest.slug)
        result.append(manifest)

    for item in sorted(_manifests.values(), key=lambda value: (value.order, value.slug)):
        visit(item)
    return result


def discover_extensions():
    for config in apps.get_app_configs():
        module = f"{config.name}.pms_extension"
        try:
            if find_spec(module):
                import_module(module)
        except (ImportError, AttributeError, ValueError) as error:
            logger.exception("Extension discovery failed for %s", module)
            _states[config.label] = {"status": "degraded", "error": str(error)}
    registries.clear()
    _states.clear()
    for manifest in _ordered_manifests():
        error = ""
        if _version(PLATFORM_VERSION) < _version(manifest.minimum_platform_version):
            error = f"Requires platform {manifest.minimum_platform_version} or newer."
        for dependency, minimum in manifest.dependencies.items():
            installed = _manifests.get(dependency)
            if installed is None:
                error = f"Missing dependency {dependency}."
                break
            if _version(installed.version) < _version(minimum):
                error = f"Dependency {dependency} must be {minimum} or newer."
                break
        if error:
            _states[manifest.slug] = {"status": "incompatible", "error": error}
            continue
        try:
            manifest.register(ExtensionContext(manifest.slug))
            _states[manifest.slug] = {"status": "ready", "error": ""}
        except Exception as exception:
            logger.exception("Extension activation failed for %s", manifest.slug)
            _states[manifest.slug] = {"status": "degraded", "error": str(exception)}
    return _states.copy()


def extension_manifests():
    return _manifests.copy()


def extension_states():
    return _states.copy()


def dispatch_event(event, payload):
    results = []
    for item in registries.event_listeners.all():
        listener_event, callback = item.value
        if listener_event == event or listener_event == "*":
            results.append(callback(event, payload))
    return results
