"""Select a settings profile through DJANGO_ENV."""

import os

profile = os.environ.get("DJANGO_ENV", "development").lower()

if profile == "production":
    from .production import *  # noqa: F403
elif profile == "test":
    from .test import *  # noqa: F403
else:
    from .development import *  # noqa: F403
