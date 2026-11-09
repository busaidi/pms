# PMS

A small property management system built with Django 5.2.

The full Laravel-to-Django feature-parity roadmap is documented in
[`PORTING_PLAN.md`](PORTING_PLAN.md).
The generated [`docs/PARITY_MATRIX.md`](docs/PARITY_MATRIX.md) assigns every
OpenKos route to a delivery phase.

The first module provides admin management for properties, units, tenants, and
leases. Monetary fields use three decimal places for Omani rial amounts.

## Local development

Development uses PostgreSQL. Set `DJANGO_DB_NAME`, `DJANGO_DB_USER`,
`DJANGO_DB_PASSWORD`, `DJANGO_DB_HOST` (defaults to `127.0.0.1`), and
`DJANGO_DB_PORT` (defaults to `5432`).

An optional Windows PostgreSQL cluster can store its data and machine-specific
connection settings in the Git-ignored `.local-postgres/` directory. If configured,
start it before running Django:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/local_postgres.ps1 start
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
```

The helper also accepts `status` and `stop`. It controls only the PMS cluster;
the separately installed PostgreSQL service on port 5432 is independent.
Keep `.local-postgres/` private and preserve it as database storage. SQLite
migration snapshots are retained under ignored `backups/`; `db.sqlite3` is no
longer used by development. Local JSON settings are loaded only by development
and its test profiles; explicit environment variables take precedence.

Production backup archives, extracted backups, database dumps, credentials, and
`media/` are ignored by Git. Local email uses the console backend. When restoring
production data for local development, isolate its database and disable outbound
integrations and webhooks before starting the application.

```bash
source .venv/bin/activate
python manage.py runserver 127.0.0.1:8000
```

Open `http://127.0.0.1:8000/admin/` and sign in with the superuser account.

## Checks

Lease registration automatically generates the approved Atheer contract. Preview
and download it from the lease workspace. See [contract generation setup](docs/CONTRACT_GENERATION.md)
for the private PDF storage, Node/Chromium runtime, and versioning behavior.

```bash
python manage.py check
python manage.py test
```

The explicit `config.settings.test` profile remains SQLite (`python manage.py
test --settings=config.settings.test`). The default development settings now
also run tests on PostgreSQL. Validate PostgreSQL behavior against
a separate, disposable `pms_test` database using:

```bash
python manage.py test --settings=config.settings.postgres_test --noinput
```

Refresh the source route inventory after an OpenKos change:

```bash
python tools/audit_openkos.py
```

When a phase passes its acceptance checks, preserve that result in the matrix:

```bash
python tools/audit_openkos.py --complete-phase 1
```

Set `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, and `DJANGO_ALLOWED_HOSTS` before a
production deployment.

## Production deployment

The production instance runs at `https://omanskylight.com` using PostgreSQL,
Gunicorn, systemd, Nginx, Redis, and Celery. Services start automatically at
boot.

```bash
sudo systemctl status pms
sudo systemctl status pms-celery pms-celery-beat redis-server
sudo journalctl -u pms -n 50
sudo systemctl restart pms
```

Useful production endpoints:

- Staff workspace: `https://omanskylight.com/`
- Public properties: `https://omanskylight.com/listings/`
- Readiness: `https://omanskylight.com/health/`
- Django administration: `https://omanskylight.com/admin/`

Identity and security features include nine OpenKos-compatible roles, 62 exact
capabilities, property-scoped access, staff invitations, password and email
verification flows, encrypted TOTP with recovery codes, WebAuthn passkeys,
encrypted secret settings, and immutable audit records.

Synchronize the canonical role definitions after an authorization change:

```bash
python manage.py sync_roles
```

OpenKos remains available only from the server at `http://127.0.0.1:8080`.
Its PHP-FPM, queue worker, and scheduler services remain enabled.

## Production deployment and contract configuration

Codex deployment runbook: [deployment/CODEX_DEPLOY.md](deployment/CODEX_DEPLOY.md).
It covers safe updates to the existing production database, private transfer of
terms/lessor settings/signatures, Chromium installation, service write permissions,
verification and rollback boundaries. By explicit owner authorization, the
production configuration bundle and checksum in `artifacts/deployment/` are
included in Git. Keep them private. Other artifacts and uploaded files are excluded.
