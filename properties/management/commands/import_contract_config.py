from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError, ObjectDoesNotExist, MultipleObjectsReturned
from django.core.management.base import BaseCommand, CommandError

from properties.contract_transfer import load_bundle, plan_import, apply_bundle


class Command(BaseCommand):
    help = "Preview add-only contract configuration import. No writes unless --apply is specified."

    def add_arguments(self, parser):
        parser.add_argument("bundle")
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--sha256")
        parser.add_argument("--database-name")
        parser.add_argument("--actor", help="Existing active superuser username for the audit trail")

    def handle(self, *args, **options):
        try:
            data, digest = load_bundle(options["bundle"])
            db = settings.DATABASES["default"]
            self.stdout.write(f"Target: {db['HOST']}:{db.get('PORT', '')}/{db['NAME']} | SHA256: {digest}")
            if options["sha256"] and options["sha256"].lower() != digest:
                raise ValueError("Bundle checksum mismatch.")
            plan = plan_import(data)
            for prop, profile, signature, add_profile, terms in plan:
                self.stdout.write(f"{prop.slug}: add profile={add_profile}, add terms={len(terms)}; identical records skipped.")
            if options["apply"]:
                if not options["sha256"] or options["database_name"] != db["NAME"] or not options["actor"]:
                    raise ValueError("Apply requires --sha256, matching --database-name and --actor.")
                actor = get_user_model().objects.get(username=options["actor"], is_active=True, is_superuser=True)
                apply_bundle(data, actor)
                self.stdout.write(self.style.SUCCESS("Applied. No existing configuration or operational records overwritten."))
            else:
                self.stdout.write("PREVIEW ONLY: no database or file changes.")
        except (OSError, ValueError, TypeError, KeyError, ValidationError, ObjectDoesNotExist, MultipleObjectsReturned) as error:
            raise CommandError(str(error)) from error
