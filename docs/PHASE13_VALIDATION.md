# Phase 13 stabilization validation

Revalidated 30 September 2026 against the Django codebase, isolated PostgreSQL
test/browser databases, and the production Atheer dataset at
`https://omanskylight.com`.

## Current results

| Area | Result |
| --- | --- |
| Django regression | 124 tests passed on PostgreSQL 18 |
| Deployment configuration | `manage.py check --deploy` passed with zero issues |
| Route parity | All 291 OpenKos routes have Django, automated-test, and browser evidence in `docs/PARITY_MATRIX.md` |
| Browser workflows | Completion smoke and phase 3–11 Playwright suites passed against disposable PostgreSQL fixtures |
| Responsive UI | Staff, public, resident, account, search, and provider pages passed at desktop and mobile sizes |
| Arabic | Public and authenticated RTL flows, saved preference, login, dashboard, profile, and mobile layout passed |
| Accessibility | No critical or serious axe WCAG A/AA findings on public, login, staff, resident, or mobile views |
| Account security | Password change/confirmation, recovery regeneration, passkey deletion, and safe account/staff deactivation covered |
| Audit | Successful authenticated model writes record sanitized before/after snapshots in immutable logs |
| Provider adapters | SMTP and WhatsApp HTTPS webhook settings, encrypted credentials, and health tests are implemented; production credentials remain operator configuration |
| Reference retention | Laravel remains local and read-only at the operator's request |

## Current backup and restore proof

`backups/completion-20260930/pms.dump` was created from production in PostgreSQL
custom format and restored into `pms_restore_completion`. The production Django
check passed against the restored database and the following counts matched:

| Check | Restored value |
| --- | ---: |
| Properties | 1 |
| Units | 26 |
| Tenants | 1 |
| Leases | 1 |
| Invoices | 3 |
| Invoice total | OMR 1,200.000 |
| Payments | 1 |
| Payment total | OMR 400.000 |

The dump SHA-256 is
`e202b8546831cc34ac68674cc4884cc023388efd697f0fe0a2f18653d7ae243c`.
The temporary restore database was removed after verification.

## Test isolation

- `config.settings.postgres_test` uses `pms_test` and validates PostgreSQL
  transactions, constraints, and row locks.
- `config.settings.browser_test` uses `pms_browser`; `seed_demo` populates only
  this disposable database for deterministic browser journeys.
- Production contains the requested Atheer building and Hamed Al Busaidi lease.
  Browser fixtures never write to production.

## Accepted implementation decisions

`docs/ACCEPTED_REPLACEMENTS.md` records the production-safe use of Django's
supported user plus `UserProfile`, history-preserving account deactivation,
Django-native extensions, consolidated workspaces, and provider adapters.

The operator explicitly requested that `admin/admin` remain available. This is
recorded as a deployment exception. External password-reset delivery requires
SMTP credentials to be entered at `/settings/mail/`; the production SMTP
integration remains disabled until those credentials are supplied, and console
delivery is rejected in production.
