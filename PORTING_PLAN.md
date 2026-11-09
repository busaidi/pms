# OpenKos Laravel to Django Feature-Parity Plan

## Document status

- **Purpose:** Rebuild every user-facing and operational OpenKos feature in the
  Django PMS, then migrate production data and retire the Laravel runtime only
  after parity is proven.
- **Django codebase:** `/home/hamed/pms`
- **Laravel reference:** `/home/hamed/OpenKos`
- **Current public application:** Django at `https://omanskylight.com`
- **Current reference application:** Laravel at `http://127.0.0.1:8080`
- **Database policy:** Django and Laravel keep separate PostgreSQL databases
  until the final migration rehearsal and cutover.
- **Plan state:** Complete and revalidated 30 September 2026. Phases 0 through 13 are deployed. Laravel remains
  local and read-only at the operator's request as a rollback reference.

## Source audit

The plan is based on the live Laravel repository, database schema, routes,
controllers, actions, React pages, schedules, permissions, and tests.

| Surface | Audited count |
| --- | ---: |
| HTTP routes | 291 |
| Eloquent models | 43 |
| Controllers | 58 |
| Domain actions | 44 |
| React/Inertia pages | 93 |
| Database migrations | 105 |
| Granular permissions | 62 |
| Feature tests | 113 |
| Unit tests | 28 |

The README understates the product surface. The migration must cover the full
application described below, not only properties, tenants, leases, and rent.

## Parity definition

A Django phase reaches parity only when all of the following are true:

1. The same business operation is available to the same user persona.
2. Validation, authorization, state transitions, and money calculations match.
3. Historical records remain protected from unsafe deletion.
4. The Django interface supports the complete workflow, including empty,
   validation-error, success, archived, and permission-denied states.
5. Equivalent automated tests pass against PostgreSQL.
6. A browser test completes the main workflow on desktop and mobile.
7. Record counts and financial totals reconcile where migrated data is involved.

Visual parity means a coherent Oman Skylight design system and equivalent
information architecture. It does not require copying React component code or
pixel-matching OpenKos.

## Product feature inventory

### Identity, security, staff, and access

- Login, logout, registration policy, email verification, password reset, and
  password confirmation.
- User profile, account deletion, active/inactive access, last login, and staff
  invitations with resend and acceptance flows.
- Two-factor authentication, recovery codes, and passkeys/WebAuthn.
- Owner bypass plus granular role permissions.
- Role create, edit, clone, delete, labels, descriptions, colors, active state,
  and permission assignment.
- Recommended Admin, Staff, Finance Staff, Front Desk, Maintenance Staff, and
  Property Manager roles.
- Property-scoped staff assignment and queryset scoping.
- Activity logs and before/after audit logs.

### Dashboards and reporting

- Portfolio overview with occupancy, property, unit, lease, tenant, invoice,
  payment, and maintenance summaries.
- Rent dashboard with due, upcoming, overdue, paid, and outstanding views.
- Financial dashboard with property/date/currency filters and revenue/expense
  aggregates.
- Consistent OMR display with three decimal places and correct minor-unit rules
  for every supported currency.
- Report permission boundaries and exportable reporting views.

### Properties, inventory, pricing, and media

- Property types, regions, cities, property CRUD, archive/restore, staff
  assignment, and property-scoped workspaces.
- Rental modes: individual units, whole property, and hybrid.
- Unit types with bedrooms, bathrooms, size, furnishing, active state, soft
  deletion, publication, galleries, amenities, and rates.
- Units with floor, size, capacity, status, type assignment, archive/restore,
  rates, lease history, maintenance history, inspection history, and utilities.
- Property-, unit-type-, and unit-level effective-dated pricing.
- Billing intervals for day, week, month, and year.
- Amenities at property and unit-type scope.
- Property and unit-type image galleries with ordering, captions/metadata, and
  private/public delivery rules.
- CSV templates, preview, validation, import, and export for properties, property
  types, units, unit rates, tenants, and expenses.

### Tenants and leasing

- Tenant CRUD, archive/restore, emergency contacts, sensitive identifiers,
  notes, documents, invitation, resend, access disable, and optional user link.
- Multiple tenants per lease with one primary tenant.
- Property, unit-type, and unit rental targets according to rental mode.
- Rate selection or custom price, currency snapshot, deposit, rent due day,
  advance/arrears billing, start/end date, and notes.
- Lease lifecycle: active, terminated, renewed, and expired/reserved behavior.
- Lease update, unit move, unit-history audit, renewal chain, termination, and
  move-out.
- Deposit settlement with deductions, refund, forfeit, and carry-forward rules.
- Rent schedule preview and lease expiration notices.
- Lease workspace for overview, documents, invoices, payments, and inspections.

### Invoicing and payments

- Scheduled and manual invoice generation with deterministic period boundaries,
  references, line items, totals, currency snapshots, and status calculation.
- Pending, partial, paid, cancelled, and void invoice states.
- Manual cash, transfer, e-wallet, and other payments.
- Pending, confirmed, and cancelled payment lifecycle.
- Payment proof upload, download, confirmation, rejection, and audit actors.
- Payment allocation across invoices with overflow protection and idempotency.
- Signed public invoice payment links.
- Printable invoices and optional generated PDF artifacts.
- Provider-independent payment gateway registry, checkout attempts, instructions,
  webhooks, signature verification, reconciliation, expiry, conflict handling,
  and exactly-once canonical payment creation.

### Maintenance and notifications

- Maintenance tickets for properties or units with location, priority, status,
  assignment, cost, resolution, and history.
- Reported → in progress → resolved/cancelled state rules.
- Unit blocking and automatic status restoration based on active leases.
- Tenant-created tickets and tenant visibility restrictions.
- In-app notifications, read/read-all behavior, email, WhatsApp, and log drivers.
- Automated upcoming, due-today, and overdue rent reminders with configurable
  intervals, templates, channels, deduplication, and manual sending.
- Lease-expiration notifications.

### Expenses and financial operations

- Expense categories and active ordering.
- Expense CRUD, receipt storage, property scope, vendor, reference, notes, and
  voiding with reason and actor.
- Recurring expenses with daily generation, interval, next-due calculation,
  pause/resume, start/end dates, and idempotency.
- Expense CSV import/export.
- Currency-aware financial dashboard calculations.

### Utilities

- Electricity, water, and custom meters per unit.
- Meter identifiers, units, rate/currency snapshots, active state, and custom
  utility names.
- Reading periods, prior/current values, calculated consumption, corrections,
  adjustment lineage, editing, and deletion rules.
- Utility billing into invoice line items without duplicate billing.

### Inspections

- Move-in, move-out, and periodic inspection templates.
- Ordered template checklist items and active/inactive templates.
- Property-, unit-, and lease-scoped inspections.
- Draft updates, item conditions, notes, damage observations, inspector,
  completion actor/time, and immutable completed records.
- Multiple photos per inspection item with private delivery and deletion rules.

### Public listings and applications

- Public property index, property detail, unit-type detail, gallery delivery,
  slugs, and publication readiness.
- Per-property and per-unit-type publish/unpublish controls.
- Public site name, homepage title/description, social image, logo, favicon, and
  SEO metadata.
- Rental applications targeting whole property or unit type.
- Application statuses: new, reviewing, accepted, rejected, withdrawn.
- Applicant details, intended move-in details, messages, operator notes,
  feedback, review audit, duplicate-open-application protection, rental offer
  snapshot, and accepted-application conversion to tenant.

### Tenant/applicant portal

- Shared portal for applicant-only, tenant-only, and staff-plus-tenant users.
- Dashboard, applications, leases, invoice history, payment history, invoice
  print/download, payment submission, payment gateway checkout, notifications,
  maintenance requests, and profile management.
- Tenant authorization restricted to linked records.

### Settings, integrations, and platform operations

- General settings: branding, site identity, country, locale, timezone, default
  currency, supported currencies, reference prefixes, and invoice PDF switch.
- Mail driver/configuration and test delivery.
- WhatsApp driver/configuration, status, pairing/health, and test delivery.
- Reminder settings and message templates.
- Payment gateway selection and encrypted provider configuration.
- Property types, amenities, expense categories, and inspection templates.
- About/build/license page.
- Dynamic typed settings contributed by extensions.
- Health endpoint, structured logs, background job failures, deployment checks,
  and protected file storage.
- Plugin extension points for navigation, dashboards, workspaces, settings,
  permissions, notification drivers, payment gateways, routes, migrations, and
  event listeners.

## Target Django architecture

### Application structure

Use a Django monolith with domain apps and explicit service functions. Views
handle HTTP concerns; services perform transactional workflows; selectors own
complex reads; model methods remain small.

```text
pms/
├── config/             settings, root URLs, ASGI/WSGI, Celery
├── accounts/           users, invitations, roles, 2FA, passkeys
├── audit/              activity and before/after audit records
├── properties/         property types, properties, units, unit types, rates
├── media_library/      private/public media and galleries
├── tenants/            tenant profiles, documents, portal identity link
├── leasing/            leases, occupancy, transfers, renewals, deposits
├── billing/            invoices, line items, payments, allocations, PDFs
├── payments/           gateway attempts, adapters, webhooks, reconciliation
├── maintenance/        tickets, transitions, assignment, unit blocking
├── expenses/           categories, expenses, recurring expenses
├── utilities/          meters, readings, corrections, invoice billing
├── inspections/        templates, inspections, items, photos
├── applications/       public applications and conversion
├── portal/             tenant/applicant self-service
├── notifications/      in-app, email, WhatsApp, reminders
├── reports/            dashboard selectors, exports, financial reporting
├── data_transfer/      CSV definitions, preview, import, export
├── settings_registry/  typed settings and encrypted integration values
└── platform_ext/       Django-native extension registries and lifecycle
```

### Technology choices

- Django 5.2 LTS and PostgreSQL.
- Django templates with HTMX and small Alpine.js controllers for sheets,
  dialogs, filters, inline actions, and optimistic refreshes. This keeps the
  application Django-native while supporting the dense OpenKos workflows.
- A shared CSS token and component layer for the application shell, tables,
  forms, workspaces, statuses, charts, and portal pages.
- Celery workers and Celery Beat with Redis for async notifications, invoice
  PDF jobs, payment reconciliation, and schedules.
- Django Groups and permissions plus explicit property memberships and scoped
  selectors. Owner remains a controlled global bypass.
- Private media served through authorized Django views; public listing assets
  use immutable public URLs.
- Adapter registries for payment, mail, and WhatsApp providers.
- Decimal storage with enough precision for OMR and other currencies;
  currency-specific minor-unit validation at service boundaries.
- PostgreSQL constraints and indexes mirror the Laravel business invariants.

### State machines that must remain centralized

| Domain | Allowed transitions |
| --- | --- |
| Lease | active → terminated; active → renewed |
| Payment | pending → confirmed; pending → cancelled |
| Maintenance | reported → in progress/cancelled; in progress → resolved/cancelled |
| Application | new → reviewing/accepted/rejected/withdrawn, subject to current validator rules |
| Unit | available/occupied/maintenance transitions driven by leases and tickets; unavailable is manual |
| Inspection | draft → completed; completed records become immutable |
| Payment attempt | provider-normalized pending/settled/failed/expired/cancelled with idempotent terminal handling |

## Delivery phases

Each phase ends with a deployable increment, database backup, migration check,
test report, and browser smoke test. The Laravel reference remains available on
localhost after completion under an enforced read-only database role.

### Implementation status — 30 September 2026

| Phase | Status | Delivered so far |
| ---: | --- | --- |
| 0 | Complete | Verified backups, Git baseline tag, 291-route matrix with Django/test/browser evidence, isolated settings |
| 1 | Complete | Responsive shell/design system, permission-scoped global search, health checks, Redis, Celery worker/beat, Playwright smoke suite |
| 2 | Complete | 62 capabilities, nine persona roles, property scope, invitations, verification/reset/change/confirmation, soft account deactivation, encrypted TOTP/recovery codes, removable WebAuthn passkeys, encrypted typed settings, immutable request and before/after model audit history |
| 3 | Complete | Scoped inventory workspaces, all rental modes, effective three-level rate histories, publication readiness, protected media, soft deletion/restore, master data, transactional CSV and verified demo fixtures |
| 4 | Complete | Scoped tenant and lease workspaces, protected documents, invitations, shared occupancy, target/rate snapshots, rent schedules, moves, renewals, termination, deposit settlement, expiration events and tenant CSV |
| 5 | Complete | Scheduled/manual invoices, status and balance engine, proof review, atomic allocation, print/PDF artifacts, signed payment links, gateway registry, webhook/reconciliation lifecycle and finance workspaces |
| 6 | Complete | Maintenance lifecycle, attachments, tenant-safe notifications, reminder delivery and schedules |
| 7 | Complete | Expenses, recurring generation, currency-aware dashboards, reports and exports |
| 8 | Complete | Utility metering/billing/corrections and immutable inspection workflows |
| 9 | Complete | Publication-safe listings, galleries, SEO/branding and full application review/conversion |
| 10 | Complete | Ownership-safe tenant/applicant portal for applications, leases, billing, maintenance, notifications and profiles |
| 11 | Complete | Encrypted SMTP and WhatsApp webhook configuration/health tests plus Django-native extension discovery, registries, lifecycle and reference extension |
| 12 | Complete | Idempotent Laravel migration, two restored rehearsals, production import, exact reconciliation and rollback runbook |
| 13 | Complete | 124 PostgreSQL tests, isolated seeded browser workflows, accessibility/RTL/security validation, monitoring, restore/load checks and read-only Laravel retention |

“In progress” means the schema or a usable vertical slice exists, but the phase
gate remains open until every listed workflow and parity test passes.

### Phase 0 — Parity specification and safe baseline

**Goal:** Make the rewrite measurable and preserve rollback paths.

- Initialize source control for the Django repository and tag the current live
  baseline.
- Back up the Django and Laravel databases, Laravel private uploads, Django
  media, and both deployment configurations.
- Create a route/feature/test parity matrix linking every Laravel page and
  mutation to its Django replacement.
- Record table counts, financial totals by currency, file counts, and active
  workflow counts from Laravel.
- Add separate development, test, staging, and production settings.
- Establish coding, migration, fixture, and release conventions.
- Mark the four current provisional Django models as replaceable; preserve only
  the PostgreSQL superuser account during schema redesign.

**Gate:** Backups restore successfully, baseline tag exists, and every Laravel
route is assigned to a future phase or explicitly documented as framework-only.

### Phase 1 — Core platform and design system

**Goal:** Establish the production foundation used by all feature modules.

- Build the responsive Oman Skylight application shell, navigation, property
  selector, search surface, notifications area, tables, forms, sheets, dialogs,
  pagination, filters, status treatment, and workspace tabs.
- Add common base models, timestamps, soft deletion, immutable audit fields,
  reference allocation, currency utilities, timezone serialization, and media
  abstractions.
- Configure Celery, Redis, worker monitoring, retry policy, and Celery Beat.
- Add structured logging, error pages, health/readiness checks, and secure
  production settings.
- Introduce pytest, factories, coverage, Playwright, accessibility checks, and
  a CI-style local verification command.

**Gate:** App shell passes desktop/mobile visual review; health, worker, beat,
PostgreSQL, static files, and authenticated navigation pass deployment tests.

### Phase 2 — Accounts, security, RBAC, settings, and audit

**Goal:** Match OpenKos identity and authorization before domain data expands.

- Use Django's supported user model with a one-to-one security/profile record;
  the production-safe rationale is recorded in `docs/ACCEPTED_REPLACEMENTS.md`.
- Implement invitations, activation, verification, password reset, profile,
  active state, last login, and safe account deletion.
- Add owner, roles, 62 granular permissions, recommended roles, role cloning,
  and property memberships.
- Add authorization mixins, scoped selectors, template permission helpers, and
  denial tests for every permission family.
- Add TOTP 2FA, recovery codes, passkeys, password confirmation, and security
  settings.
- Add typed settings, encrypted secret values, branding, locale/timezone,
  currencies, prefixes, and build/about information.
- Add activity and before/after audit logs.

**Gate:** Owner, admin, staff, finance, front-desk, maintenance, property-manager,
and tenant/applicant personas pass their allow/deny test matrix.

### Phase 3 — Properties, units, pricing, amenities, galleries, and CSV

**Goal:** Complete the inventory/master-data foundation.

- Implement regions, cities, property types, property rental modes, properties,
  unit types, units, amenities, property memberships, soft deletion, and restore.
- Implement property, unit-type, and unit rate histories with effective dates,
  currencies, intervals, active state, and rate resolution precedence.
- Implement unit statuses, availability selectors, capacity, furnishing, and
  bulk unit-type assignment.
- Implement property/unit-type galleries, ordering, metadata, authorized media,
  and image validation.
- Build list, detail, create/edit, workspace, pricing, units, unit types, and
  archived views.
- Implement CSV template, preview, transactional import, error reporting, and
  export for property types, properties, units, and unit rates.

**Gate:** Inventory fixtures reproduce the OpenKos demo shape; all rental modes,
rate precedence, soft-delete restrictions, CSV round trips, and media workflows
pass.

**Completed 29 September 2026.** Four live demo properties cover unit,
whole-property, and hybrid rental modes. Automated tests verify effective-date
filtering, unit-over-unit-type precedence, publication readiness, archive
restrictions, property scope, image validation, and transactional CSV behavior.
The production browser smoke covers desktop/mobile inventory, pricing, master
data, CSV export, public property listings, and public unit-type details.

### Phase 4 — Tenants and complete lease lifecycle

**Goal:** Support occupancy and every lease transition before billing.

- Implement tenants, sensitive data permissions, documents, archive/restore,
  invitations, user linking, access disable, and tenant CSV transfer.
- Implement multi-tenant leases, primary tenant, rental target, pricing snapshot,
  deposits, advance/arrears billing, rent due day, and occupancy rules.
- Add lease creation for unit, unit type, and whole-property modes.
- Add updates, unit move with history, termination, renewal chain, move-out,
  deposit settlement/deductions, refund/forfeit/carry-forward, and rent schedule.
- Build global lease list and property/unit/tenant/lease workspace views.
- Add lease-expiration selection and notification events.

**Gate:** Laravel lease transition, occupancy, renewal, deposit, and financial
checker cases have equivalent Django tests and produce the same results.

**Completed 29 September 2026.** The live Django application now supports
tenant records and private documents, invitations and account linking,
property-scoped access, shared occupancy, unit/unit-type/whole-property lease
creation, immutable pricing snapshots, advance and arrears rent schedules,
moves, termination, renewals, move-out, and complete deposit allocation. The
38-test suite covers occupancy conflicts, capacity, schedule boundaries,
invoiced-period preservation, renewal balances and deposit behavior. Live
desktop/mobile browser checks cover tenant records, lease workspaces,
whole-property daily schedules, expiration selection, and CSV transfer.

### Phase 5 — Invoices, payments, PDFs, and gateway lifecycle

**Goal:** Reach accounting parity with strict transactional integrity.

- Implement invoice generation for advance and arrears strategies, references,
  periods, due dates, line items, totals, and status recalculation.
- Add daily invoice generation with overlap/idempotency protection.
- Implement manual payments, proof files, verify/reject, payment allocations,
  overflow protection, actor tracking, and currency snapshots.
- Add signed payment links, invoice print view, and queued PDF artifact creation.
- Implement payment gateway registry, attempts, checkout instructions, webhook
  verification, normalized results, reconciliation, expiry, anomaly logging, and
  exactly-once canonical settlement.
- Build staff invoice/payment workspaces and all audit/history states.

**Gate:** For identical fixtures, Laravel and Django agree on invoice periods,
totals, outstanding balances, allocations, and status transitions by currency.

**Completed 29 September 2026.** Period invoices are generated idempotently to
the same two-month horizon as OpenKos, with currency and lease snapshots,
deterministic period uniqueness, background PDF artifacts, and status
recalculation from confirmed allocations. Manual receipts, private proof files,
confirmation/rejection, overpayment rollback, signed public checkout, gateway
configuration, expiring attempts, HMAC webhooks, reconciliation, anomaly logs,
and exactly-once settlement are live. The demo ledger reconciles to 51 invoices
totalling OMR 42,235.000 and one confirmed OMR 725.000 payment. Fifty-one automated
tests and live desktop/mobile billing journeys pass.

### Phase 6 — Maintenance, reminders, and notifications

**Goal:** Port daily operational communication and ticket handling.

- Implement maintenance CRUD, priorities, assignment, state validation, costs,
  resolution, property/unit history, and automatic unit blocking/restoration.
- Add in-app notifications and read tracking.
- Add notification event pipeline and log, SMTP, and WhatsApp adapters.
- Implement reminder configuration, templates, channel selection, upcoming,
  due-today, overdue scheduling, deduplication logs, and manual send.
- Schedule daily reminders and lease-expiration notifications.

**Gate:** Transition tests, reminder scheduler cases, deduplication, driver
failures, tenant notifications, and unit-state side effects match OpenKos.

**Completed 29 September 2026.** Maintenance now has property-scoped list and
workspace views, generated references, private attachments, assignments, cost
tracking, strict reported/in-progress/resolved/cancelled transitions, status
history, tenant updates, and transactional unit blocking/restoration. In-app
notifications support unread counts, individual read, and read-all behavior.
Configurable upcoming, due-today, overdue, manual, and lease-expiration notices
run through database, email, WhatsApp, and log adapters with per-channel
deduplication and recorded failures. The complete 62-test suite and live
desktop/mobile maintenance, notification, and reminder browser checks pass.

### Phase 7 — Expenses, recurring costs, financial dashboards, and reports

**Goal:** Complete owner/finance operational reporting.

- Implement expense categories, expenses, receipts, editing, voiding, actors,
  filters, import/export, and property/currency scoping.
- Implement recurring expenses, interval calculations, pause/resume, next due,
  daily generation, and idempotency.
- Build overview, rent, and financial dashboards with equivalent selectors and
  calculations.
- Add date/property/currency filters, report permission checks, downloadable
  reports, and reconciliation totals.

**Gate:** Dashboard calculator fixtures and revenue/expense/outstanding totals
match Laravel for every supported currency and filter combination.

**Completed 29 September 2026.** The live application now provides a scoped
expense register with receipts, editing, immutable currency/source snapshots,
reasoned voiding, category settings, CSV preview/import/export, and
daily/weekly/monthly/yearly recurring schedules with pause/resume and
idempotent catch-up generation. Financial and rent dashboards filter by
property, period, currency, and urgency while reconciling billed revenue,
confirmed allocations, outstanding balances, costs, NOI, and occupancy. The
demo YTD report reconciles OMR 33,525.000 billed, OMR 725.000 collected, OMR
85.000 costs, and OMR 33,440.000 NOI. All 71 tests and live desktop/mobile
expense, CSV, financial, and rent-report checks pass.

### Phase 8 — Utilities and inspections

**Goal:** Complete advanced property operations.

- Implement utility meters, readings, period continuity, consumption, edits,
  corrections, lineage, validation, and deletion restrictions.
- Bill readings into invoice line items with rate/currency snapshots and
  duplicate prevention.
- Implement inspection templates and ordered checklist items.
- Implement property/unit/lease inspections, draft editing, conditions,
  completion locking, damage observations, actors, and item photos.
- Build utility and inspection workspace screens.

**Gate:** Utility billing/correction cases and inspection completion/media cases
match the Laravel test suite behavior.

**Completed 29 September 2026.** Unit utility workspaces now manage electricity,
water, and named custom meters with rate/currency snapshots, chronological
reading chains, calculated periods and consumption, immutable billed/dependent
rows, correction lineage, and exactly-once invoice line billing. Inspection
templates snapshot ordered checklist content into property/unit/lease records;
drafts support conditions, notes, damage observations, and private photos, then
become immutable after a fully assessed completion. The 80-test suite and live
desktop/mobile utility, inspection, template, and checklist journeys pass.

### Phase 9 — Public listings, SEO, and applications

**Goal:** Recreate the public acquisition flow.

- Build the public property index, property page, unit-type page, responsive
  galleries, availability/pricing summaries, and published asset delivery.
- Implement slug allocation, publication readiness, publication controls, SEO,
  Open Graph metadata, public branding, favicon, and social image.
- Implement application submission, duplicate-open protection, status workflow,
  operator review, applicant feedback, offer snapshot, withdrawal, and accepted
  application conversion to tenant.

**Gate:** Unpublished/incomplete inventory never leaks; application transition,
conversion, SEO, and public media parity tests pass.

**Completed 29 September 2026.** The public acquisition site now exposes only
publication-ready inventory, with responsive property and unit-type pages,
public gallery delivery, canonical/Open Graph metadata, and configurable public
branding. Applications snapshot the selected offer, prevent duplicate open
submissions, enforce review and withdrawal transitions, preserve review audit
details, and convert accepted applicants to tenants idempotently. The 87-test
suite, production reconciliation, and live desktop/mobile browser journeys pass.

### Phase 10 — Tenant and applicant portal

**Goal:** Deliver full self-service separate from staff administration.

- Add portal routing and navigation for applicant-only, tenant-only, and dual
  staff/tenant identities.
- Implement portal dashboard, application tracking, leases, invoice history,
  payment history, invoice print/download, proof upload, gateway checkout,
  maintenance requests, notifications, and profile management.
- Enforce record ownership on every portal selector, download, and mutation.
- Add invitation acceptance and first-login experience.

**Gate:** Cross-tenant access tests pass for every object; the complete tenant
journey works on mobile and desktop.

**Completed 29 September 2026.** A separate responsive resident portal now
supports applicant-only, tenant-only, and dual staff/tenant identities. Linked
users can track or withdraw applications; view leases, rent schedules, invoices,
payments, and notifications; print/download invoices; submit payment proof or
start gateway checkout; report and track maintenance; and update their profile.
Invitation acceptance signs the tenant directly into the first-login portal.
Ownership selectors protect every view, download, and mutation; the 95-test
suite includes cross-tenant denial coverage and the live desktop/mobile journey
passes.

### Phase 11 — Integrations and Django-native extension platform

**Goal:** Replace OpenKos integration registries and plugin seams.

- Implement registries for navigation, dashboard pages, workspace tabs, settings
  pages, permissions, notification drivers, and payment gateways.
- Implement Django `AppConfig`-based extension discovery, dependency/version
  validation, ordered registration, migrations, and event listeners.
- Add extension management/status UI and permission synchronization.
- Port required installed OpenKos plugins as Django packages.
- Add provider health/test surfaces and safe encrypted configuration.

**Important compatibility rule:** PHP/Composer runtime ZIP plugins cannot execute
inside Python/Django. Feature parity will use a Django-native plugin contract.
Every plugin actually used in production must be ported or replaced; binary
compatibility with Laravel plugins is impossible.

**Gate:** A reference Django extension exercises every registry and lifecycle
point; required production integrations pass sandbox and failure tests.

**Completed 29 September and revalidated 30 September 2026.** Installed Django apps can contribute ordered
navigation, dashboard, workspace, settings, permission, notification, payment,
route, migration, and event-listener registrations through versioned manifests.
Discovery validates platform/dependency versions, records degraded states,
synchronizes permissions, and exposes protected lifecycle and health views.
Provider configuration rejects plain-text secret keys and stores supplied tokens
with the encrypted settings backend. Dedicated settings now configure SMTP and
WhatsApp HTTPS webhooks, including encrypted credentials and health tests. The
Laravel runtime reports no installed plugins; the audit is recorded in
`docs/PLUGIN_AUDIT.md`. The reference extension exercises every registry, and
the PostgreSQL, event, health, failure, and mobile tests pass.

### Phase 12 — Data migration rehearsal and production cutover

**Goal:** Move all real OpenKos data and files with a tested rollback path.

- Build idempotent Laravel-to-Django migration commands with legacy ID maps.
- Migrate accounts, roles, property memberships, settings, master data,
  properties, inventory, rates, tenants, leases, histories, deposits, invoices,
  line items, payments, allocations, attempts, expenses, utilities, inspections,
  applications, notifications, audit history, and media metadata.
- Copy private/public files and verify checksums, MIME types, ownership, and
  authorization.
- Preserve Laravel bcrypt passwords through a transitional Django password
  hasher and upgrade hashes on successful login.
- Require re-enrollment for passkeys and 2FA unless a separately proven secure
  migration is available. Encrypted provider credentials should be re-entered
  or exported through a controlled Laravel command; they must never be copied as
  unusable ciphertext.
- Run at least two full migration rehearsals from restored production backups.
- Compare table counts, orphan checks, lease occupancy, invoice totals, payment
  allocations, outstanding balances, expense totals, file checksums, and random
  record samples.
- Enter a short Laravel write freeze, take final backups, run final migration,
  execute smoke tests, switch traffic, and retain Laravel read-only locally.
- Document and rehearse rollback before cutover.

**Gate:** Reconciliation is exact or every intentional difference is signed off;
critical browser journeys and scheduled jobs pass; rollback remains possible.

**Completed 29 September 2026.** The read-only source importer covers identity,
roles, property scope, settings, master data, inventory, rates, tenants, leases,
billing, operations, notifications, audit history, and every currently empty
source domain, with restart-safe legacy IDs. Laravel bcrypt hashes upgrade after
successful Django login; 2FA/passkeys and provider secrets follow the explicit
re-enrollment/re-entry rule. Two clean PostgreSQL rehearsals restored from the
same source dump, an idempotency repeat, the production dry run, and production
cutover all produced zero count, invoice-total, payment-total, and active-lease
differences across 1,522 mapped rows. All 104 tests and all desktop/mobile
critical browser journeys pass. Checksummed source/target backups and the
rehearsed rollback procedure are retained, and Laravel remains available on
localhost.

### Phase 13 — Stabilization and Laravel retirement

**Goal:** Prove production reliability before removing the reference runtime.

- Monitor errors, job failures, payment anomalies, email/WhatsApp delivery,
  database performance, storage growth, and slow queries.
- Complete security review, dependency audit, backup restore drill, load test,
  accessibility review, and mobile browser review.
- Resolve parity-matrix gaps and production regressions.
- Keep Laravel local and read-only through the agreed observation window.
- Remove Laravel services only after the owner accepts reconciliation and the
  final rollback deadline passes. Preserve archival database and media backups.

**Gate:** No open critical/high defects, restores are proven, scheduled jobs are
healthy, and the parity matrix is complete.

**Completed 29 September and revalidated 30 September 2026.** Production monitoring reports database,
Redis, payment, delivery, extension, and storage health in one machine-readable
command. Django logs application events as JSON; Nginx enforces HSTS preload and
rate-limits both login endpoints. A clean backup restored into a separate
PostgreSQL database with exact counts and financial totals. The 124-test suite
passes on PostgreSQL 18. Deterministic phase 3–11 and completion browser
workflows, Arabic RTL checks, and an axe WCAG A/AA audit pass against an isolated
database. A read-only production smoke covers the account, provider, Atheer
search, password-reset, lease-move, maintenance-transition, invoice, and PDF
paths. SMTP and WhatsApp webhook adapters are ready for operator credentials.
The prior dependency audits and 400-request concurrent load smoke remain valid.
All 291 source routes remain mapped. Laravel returns HTTP 200 only on localhost,
its application database role is read-only, and its queue and scheduler are
disabled. The operator explicitly chose to retain that local reference, so its
services and archival data have not been removed.

## Background schedule mapping

| Laravel schedule | Django replacement |
| --- | --- |
| Daily 01:00 invoice generation | Celery Beat task with distributed lock |
| Daily 01:05 recurring expenses | Celery Beat task with distributed lock |
| Every 5 minutes payment reconciliation | Celery Beat task with per-attempt idempotency |
| Daily 08:00 rent reminders | Celery Beat task in configured application timezone |
| Daily 08:05 lease expiration notices | Celery Beat task in configured application timezone |

## Data and security migration rules

- Laravel remains the source of truth until Phase 12 cutover.
- No phase writes directly into the Laravel production database.
- Every migration command is restartable and records source table/source ID.
- Financial rows are append-only after migration except through explicit domain
  correction workflows.
- Soft-deleted business records migrate with deletion timestamps.
- Foreign-key delete behavior is recreated deliberately: historical records use
  `PROTECT`, dependent artifacts use `CASCADE`, and user audit actors use
  `SET_NULL`.
- Monetary values migrate as decimal strings, never floats.
- Currency, rate, and amount snapshots remain attached to historical rows.
- Sensitive identifiers and integration settings are never written to logs.
- Private media is inaccessible without an authorized view.
- The operator explicitly requires the current `admin/admin` credential to
  remain available. This documented operator exception supersedes the planned
  credential rotation for this deployment.

## Testing strategy

### Test layers

- **Unit:** money conversion, period calculations, reference allocation,
  validators, state transitions, reminder schedule, rate resolution.
- **Service/integration:** every transactional action against PostgreSQL.
- **Authorization:** allow/deny matrix for roles, property membership, portal
  ownership, private media, and sensitive exports.
- **HTTP:** forms, filters, pagination, files, redirects, HTMX fragments, error
  handling, webhooks, signed links.
- **Parity fixtures:** run equivalent Laravel and Django scenarios and compare
  state snapshots and financial totals.
- **Browser:** staff and tenant critical journeys on desktop and mobile.
- **Operations:** worker retry, schedule overlap, health checks, backup restore,
  deployment restart, and rollback.

### Critical browser journeys

1. Owner creates property → unit type → units → rates → publishes listing.
2. Staff creates tenant → lease → invoice → payment → confirmation.
3. Tenant accepts invitation → views invoice → uploads proof → sees confirmation.
4. Staff moves, renews, and moves out a tenant with deposit settlement.
5. Tenant reports maintenance → staff assigns/resolves → unit status recovers.
6. Utility reading produces one correct invoice line item.
7. Move-in inspection is completed with photos and becomes immutable.
8. Public applicant submits → operator accepts → converts to tenant.
9. Recurring expense and invoice schedules remain idempotent after retries.
10. Payment webhook duplicates and conflicts never double-count revenue.

## Release strategy

- Develop each phase behind URL/module visibility controls until its gate passes.
- Deploy schema additions before code that depends on them.
- Run migrations and checks, collect static assets, restart workers, then reload
  Gunicorn with a documented rollback command.
- Back up PostgreSQL before each production migration.
- Keep the last known-good service unit and application revision available.
- Update the parity matrix and this plan at the end of every phase.

## Decisions to confirm before Phase 1

1. **Frontend:** this plan recommends Django templates + HTMX + Alpine.js rather
   than recreating the React/Inertia frontend. Business and interaction parity
   remain required.
2. **Plugins:** accept Django-native extension parity; PHP plugin binaries cannot
   be reused.
3. **Authentication migration:** accept transitional Laravel bcrypt login, with
   2FA/passkey re-enrollment.
4. **Public admin password:** the operator explicitly chose to retain
   `admin/admin`; review this deployment exception before broader staff access.
5. **Rollout:** keep Laravel local/read-only through the stabilization window.

## Completion criteria

The rewrite is complete only when:

- Every item in the feature inventory is implemented or has a documented,
  accepted replacement.
- All 291 Laravel routes are mapped to Django behavior or identified as
  framework/internal routes with no missing user capability.
- The 62-permission access matrix passes.
- Financial and occupancy reconciliation passes on the final migrated dataset.
- Required production plugins/integrations have Django replacements.
- Staff and tenant critical journeys pass in browser automation.
- Backups, restore, deployment, monitoring, and rollback procedures are tested.
- Laravel has remained available long enough to satisfy the agreed rollback
  window and is retired only with explicit owner approval.
