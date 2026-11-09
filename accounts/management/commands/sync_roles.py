from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import Capability, GroupProfile, PropertyAccess
from accounts.permissions import PERMISSIONS, ROLE_DEFINITIONS, label_for


class Command(BaseCommand):
    help = "Synchronize the 62 OpenKos capabilities and recommended roles"

    @transaction.atomic
    def handle(self, *args, **options):
        capabilities = {}
        for name, description in PERMISSIONS.items():
            capabilities[name], _created = Capability.objects.update_or_create(
                name=name,
                defaults={"label": label_for(name), "description": description},
            )
        for name, (label, description, color, permission_names) in ROLE_DEFINITIONS.items():
            group, _created = Group.objects.get_or_create(name=name)
            GroupProfile.objects.update_or_create(
                group=group,
                defaults={"label": label, "description": description, "color": color, "is_system": name == "owner", "is_active": True},
            )
            group.pms_capabilities.set(capabilities[item] for item in permission_names)
        legacy_aliases = {
            "Owner": "owner",
            "Accountant": "finance-staff",
            "Maintenance": "maintenance-staff",
            "Property Manager": "property-manager",
            "Tenant": "tenant",
        }
        for legacy_name, canonical_name in legacy_aliases.items():
            legacy = Group.objects.filter(name=legacy_name).first()
            if not legacy:
                continue
            canonical = Group.objects.get(name=canonical_name)
            for user in legacy.user_set.all():
                user.groups.add(canonical)
            for access in legacy.property_access.select_related("user", "property"):
                PropertyAccess.objects.update_or_create(
                    user=access.user,
                    property=access.property,
                    defaults={"group": canonical},
                )
            legacy.delete()
        self.stdout.write(self.style.SUCCESS(f"Synchronized {len(capabilities)} capabilities and {len(ROLE_DEFINITIONS)} roles."))
