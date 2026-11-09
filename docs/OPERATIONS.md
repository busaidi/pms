# Oman Skylight operations runbook

## Runtime layout

Django serves `https://omanskylight.com` through Nginx and Gunicorn. PostgreSQL
stores application data, Redis backs Celery, and the `pms-celery` and
`pms-celery-beat` services run jobs and schedules. OpenKos remains reachable
only at `http://127.0.0.1:8080` as a reference. Its PostgreSQL role has
`default_transaction_read_only=on`; its queue and scheduler are disabled.

## Routine health checks

Run this command as the `pms` service account with the production environment:

```bash
python manage.py platform_status --fail-on-degraded
```

The JSON result covers PostgreSQL size, connections, deadlocks and active
queries over five seconds; Redis availability; payment anomalies and stale
attempts; recent failed reminder delivery; extension degradation; and free
storage. A non-zero exit means at least one check is degraded or critical.

Check service state and Celery separately:

```bash
systemctl is-active pms pms-celery pms-celery-beat nginx postgresql redis-server
celery -A config inspect ping
```

Review `journalctl -u pms`, `journalctl -u pms-celery`, and
`journalctl -u pms-celery-beat`. Django application entries are JSON. Gunicorn
access entries remain in their native access-log format. Review
`/var/log/nginx/pms-error.log` for proxy or static-file errors.

Recommended monitoring cadence:

| Check | Cadence | Escalation |
| --- | --- | --- |
| HTTP health, Redis, workers | Every minute | Any failed check |
| `platform_status --fail-on-degraded` | Every five minutes | Any non-zero exit |
| Failed jobs and delivery | Hourly | Any repeated failure |
| Payment anomalies/stale attempts | Every five minutes | Any anomaly or attempt over 24 hours |
| Database deadlocks/slow active queries | Every five minutes | Any new deadlock or query over five seconds |
| Storage free space | Hourly | Below 20%; critical below 10% |
| Dependency audit | Weekly and before release | Critical/high advisory |
| Restore drill | Monthly and before a migration release | Any checksum or reconciliation difference |

## Scheduled work

Celery Beat generates invoices daily at 01:00, recurring expenses at 01:05,
reconciles payments every five minutes, sends rent reminders daily at 08:00,
and checks lease expirations daily at 08:05 in the configured application
timezone. Tasks use locks and idempotency keys so retries cannot duplicate
financial rows.

## Backup and restore

Take a daily custom-format PostgreSQL dump and archive Django media. Retain a
weekly copy off the server according to the owner's retention policy. Record a
SHA-256 manifest with each snapshot. Before schema or migration releases, also
archive the OpenKos database and storage, Nginx configuration, and service
units. Follow `docs/MIGRATION_RUNBOOK.md` for the tested restore order.

Restore drills must use a separately named database. Compare property, unit,
tenant, lease, invoice, and payment counts plus invoice/payment totals before
dropping the drill database. Never restore over the live database to test a
backup.

## Security and dependency maintenance

Run Django's production check, Python dependency audit, and Composer audit on
the retained local reference before releases. HSTS preload, secure cookies,
TLS redirect, clickjacking protection, MIME protection, and login throttling
are enabled. The retained Laravel dependency tree has one accepted low-severity
`web-auth/webauthn-lib` advisory involving fake credentials with an empty
secret. Laravel is local-only and read-only; reassess the exception if it is
ever upgraded or exposed.

The operator explicitly requested that the `admin/admin` credential remain in
place. Treat this as a deployment exception and reassess it before granting
broader staff or network access.

## Laravel reference controls

The OpenKos Nginx server listens on `127.0.0.1:8080`. Do not publish or proxy
that port. Keep `openkos-queue.service` and `openkos-scheduler.timer` disabled.
The PHP-FPM AppArmor local rule permits read access to the source and write
access only to Laravel storage/cache paths. Verify the database safeguard with:

```sql
SELECT rolconfig FROM pg_roles WHERE rolname = 'openkos';
```

The result must include `default_transaction_read_only=on`. Removing the
reference runtime or its archives requires explicit owner approval.
