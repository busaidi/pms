from django.core.management.base import BaseCommand

from integrations.services import synchronize_extensions


class Command(BaseCommand):
    help = "Discover Django PMS extensions and synchronize lifecycle and permission metadata"

    def handle(self, *args, **options):
        extensions = synchronize_extensions()
        ready = sum(item.status == "ready" for item in extensions)
        self.stdout.write(self.style.SUCCESS(f"Synchronized {len(extensions)} extension(s); {ready} ready."))
