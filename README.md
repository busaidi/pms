# PMS

A small property management system built with Django 5.2.

The full Laravel-to-Django feature-parity roadmap is documented in
[`PORTING_PLAN.md`](PORTING_PLAN.md).
The generated [`docs/PARITY_MATRIX.md`](docs/PARITY_MATRIX.md) assigns every
OpenKos route to a delivery phase.

The first module provides admin management for properties, units, tenants, and
leases. Monetary fields use three decimal places for Omani rial amounts.

## Local development

```bash
source .venv/bin/activate
python manage.py runserver 127.0.0.1:8000
```

Open `http://127.0.0.1:8000/admin/` and sign in with the superuser account.

## Checks

```bash
python manage.py check
python manage.py test
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
