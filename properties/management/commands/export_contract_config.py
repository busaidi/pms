import hashlib
import json
import os
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from properties.contract_transfer import export_bundle, MAX_BUNDLE
from properties.models import Property


class Command(BaseCommand):
    help = "Export contract terms, lessor profiles and signatures only. Treat output as private."

    def add_arguments(self, parser):
        parser.add_argument("output")
        parser.add_argument("--property", action="append", dest="slugs")

    def handle(self, *args, **options):
        path = Path(options["output"])
        if not path.name.endswith(".contract-bundle.json"):
            raise CommandError("Use a .contract-bundle.json filename (excluded from Git).")
        properties = Property.objects.filter(archived_at__isnull=True)
        if options["slugs"]:
            properties = properties.filter(slug__in=options["slugs"])
            if properties.count() != len(set(options["slugs"])):
                raise CommandError("One or more property slugs were not found.")
        try:
            data = export_bundle(properties)
            if not data["properties"]:
                raise ValueError("No contract configuration to export.")
            raw = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
            if len(raw) > MAX_BUNDLE:
                raise ValueError("Bundle exceeds 20 MB; export one property at a time.")
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(raw)
        except (OSError, ValueError) as error:
            raise CommandError(str(error)) from error
        self.stdout.write(f"Exported {len(data['properties'])} properties. SHA256: {hashlib.sha256(raw).hexdigest()}")
