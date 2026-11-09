from pathlib import Path

from django.conf import settings
from django.core.files.storage import FileSystemStorage


def contract_storage():
    # Outside MEDIA_ROOT: PDFs are served only by the permission-checked view.
    return FileSystemStorage(location=getattr(settings, "LEASE_CONTRACT_ROOT", Path(settings.BASE_DIR) / "private-contracts"))
