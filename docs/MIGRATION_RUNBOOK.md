# OpenKos to Django migration and rollback runbook

## Source and target

- Laravel source remains available only at `http://127.0.0.1:8080`.
- Django serves `https://omanskylight.com` from PostgreSQL database `pms`.
- The migration reads Laravel through a mode-0600 DSN file. The DSN and provider
  credentials must never be passed in command output, reports, or Git.
- Every imported row receives an `openkos` legacy mapping. Repeating the command
  reuses that mapping instead of creating a duplicate.

## Final snapshot

The Phase 12 snapshot is
`backups/pre-phase12-20260929-101330/`. `SHA256SUMS` covers the Django and
Laravel custom-format PostgreSQL dumps, both media archives, Nginx output, and
the three Django service units.

## Migration

1. Put a current Laravel PostgreSQL DSN in a root/operator-readable mode-0600
   file and make a new custom-format source dump.
2. Back up target PostgreSQL and both file stores, then verify their checksums.
3. Apply Django schema migrations.
4. Run a rollback rehearsal first:

   ```bash
   python manage.py migrate_openkos \
     --source-dsn-file /secure/openkos.dsn \
     --dry-run --report /secure/dry-run.json
   ```

5. Stop `pms`, `pms-celery`, and `pms-celery-beat` for the short target write
   freeze. Keep PostgreSQL, Redis, Nginx, and localhost Laravel running.
6. Run the same command without `--dry-run`, save its JSON report, run
   `sync_extensions`, and start all three Django services.
7. Run `--reconcile-only`, the full Django test suite, all browser journeys, and
   service/health checks.

## Credential handling

Laravel `$2y$` password hashes are stored with the `laravel_bcrypt` marker. A
successful Django login verifies the hash and immediately upgrades it to the
default PBKDF2 format. Passkeys and two-factor secrets are deliberately not
copied. Sensitive provider values must be re-entered through encrypted Django
settings; source ciphertext is never copied.

## Rollback

1. Stop the three Django services.
2. Preserve the failed target as a separate custom-format dump for diagnosis.
3. Drop and recreate only the `pms` target database, then restore `pms.dump`
   from the pre-cutover directory with `pg_restore`.
4. Restore `django-media.tar.gz` into `/home/hamed/pms/media` and verify the
   recorded checksum and ownership.
5. Apply the code revision recorded immediately before Phase 12, run
   `manage.py check --deploy`, and start the services.
6. Verify `/health/`, staff login, public listings, and the resident portal.
7. Laravel stays on localhost throughout rollback; no Laravel database restore
   is needed unless its read-only reference copy is damaged. Its source dump and
   storage archive are included in the same snapshot.

Never drop or overwrite the `openkos` source database during target rollback.
