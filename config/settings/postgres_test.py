"""Test settings that exercise PostgreSQL locking, constraints, and SQL."""

import os

from .test import *  # noqa: F403
from .base import postgres_database


DATABASES = postgres_database()
DATABASES["default"]["CONN_MAX_AGE"] = 0
DATABASES["default"]["TEST"] = {
    "NAME": os.environ.get("DJANGO_TEST_DB_NAME", "pms_test"),
}
