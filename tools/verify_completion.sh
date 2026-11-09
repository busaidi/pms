#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
.venv/bin/python manage.py check
.venv/bin/python tools/build_ar_locale.py
.venv/bin/python manage.py test --settings=config.settings.postgres_test --keepdb
.venv/bin/python manage.py check --deploy --settings=config.settings.production

echo "Completion verification passed."
