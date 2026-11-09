# Lease contract generation

## Approved default layout

The current generation engine is `atheer-v9`. It retains the approved cover,
Tajawal fonts and signatures below, with editable, property-scoped terms templates.
Manage templates at `/contract-terms/` using the self-hosted Quill 2.0.3 editor
(BSD license; the user selected this free alternative to CKEditor).
Users with `properties.update` can create, copy, edit and disable templates;
`leases.create` / `leases.update` govern selecting them for a lease.
The approved 35 articles seed each property's default template automatically.
Each generated contract stores the selected template id, name, revision and
sanitized HTML in its immutable snapshot. Edits never rewrite older PDF/HTML
revisions. Stale concurrent editor submissions are rejected. Template mutations
are captured by the existing audit middleware.

Content supports headings, emphasis, paragraphs, lists and blockquotes, with
server-side HTML sanitization. It is never interpreted as Django template code.
The shared pagination script measures embedded fonts, retains all text and
splits oversized blocks while preserving inline formatting. Page counts follow
the content (the seeded default currently produces seven pages). Preview CSP
permits only the exact trusted pagination script hash; PDF rendering blocks all
external requests and runs only the trusted pagination routine.
Run `python manage.py migrate` and `npm ci` when installing this version.
Quill's browser JS/CSS and BSD license are vendored in `static/vendor/quill/`;
they are copied from the pinned npm package, so the editor works without a CDN.
Quill 2.0.3 has an upstream HTML-export advisory (CVE-2025-15056). Exported HTML
is only sent as a form value, never inserted into a live DOM directly. Bleach
sanitizes it on save and snapshot creation; links, images, styles and all HTML
attributes are disallowed. The regression suite covers active-content stripping.

The user explicitly approved `atheer-v8` as the default for all contracts generated
by the system: standalone cover and embedded Tajawal Arabic font. The approved
visual reference is the owner's approved cover-and-font revision.
`contract_services.TEMPLATE_VERSION` selects this version for registration,
renewal and generation from current data. It uses seven A4 pages, including a
standalone cover, embedded Tajawal regular/bold (bundled with its OFL license),
12-point general terms, all 35 approved articles in `terms_v6.html`, the approved lessor signature
and blank tenant signature fields. No signature-image insertion date is shown.
Earlier issued revisions keep their original templates and files.

The owner selected the approved Atheer stay template. New leases create a
versioned snapshot automatically; the registration view generates its PDF before
redirecting to the lease workspace. Renewal creates a snapshot too. Existing
leases have a **Generate from current data** action. The workspace exposes preview,
download and the previous versions. A renderer failure preserves the registered
lease and snapshot, shows a warning and permits retrying the download.

Configure the property's lessor name/contact and building details through
**Contract template settings** (requires `properties.update`). These defaults are
stored in the database, never committed as production identity data. Blank fields
remain blank. Lease notes and tenant signatures are not copied into generated contracts.
The property's approved lessor signature is stored privately in its contract profile
and embedded in each new snapshot. Changing/removing it does not rewrite previous
versions. It is an authorized signature image, not a cryptographic digital signature.

The form's end date is the **last rental day**, inclusive, matching the existing
schedule generator. Contract departure is the day after the last scheduled rental
day. This also respects existing short-stay records whose end dates were entered
as departure dates but whose schedules already exclude that day. The document
shows both dates explicitly and totals the non-waived schedule, separately from
the security deposit. Open-ended leases are flagged and not assigned a fabricated
fixed term or total.

Every changed snapshot creates a new revision; repeating generation with identical
data reuses the current version. Later tenant/default changes do not rewrite issued
copies. Historical uploads remain untouched. Template v2 uses literal, selectable
HTML text for all nine general-terms pages, with no booking variables; see
[the drafting review](CONTRACT_TERMS_REVIEW.md). Contract data and signatures remain
on their own pages. Template v1 retains its clean rendered assets for historical
copies. Neither template carries invisible stale invoice/identity PDF layers.

## Runtime and deployment

The renderer requires Node.js and the pinned Playwright Chromium. Install these
for the **same operating-system user that runs Django**:

```bash
npm ci
npx playwright install --with-deps chromium
python manage.py migrate
```

On Windows use `npx playwright install chromium`. Set `CONTRACT_NODE_EXECUTABLE`
in Django settings if `node` is not on the service PATH. When using
`PLAYWRIGHT_BROWSERS_PATH`, preserve the same value for install and runtime.
Rendering has a 75-second deadline and blocks external network requests. The HTML
is built only from escaped server templates. Oversized dynamic content fails
generation rather than silently clipping into another page.

Generated PDFs live outside `MEDIA_ROOT`, in ignored `private-contracts/` by
default. `LEASE_CONTRACT_ROOT` in Django settings can select another private,
writable directory. Back it up with the database; do not expose it via nginx/static
file serving. Downloads and previews enforce `leases.view` property access and
private/no-store responses; explicit generation requires `leases.update`.

Local development was configured and tested only. These commands have not been
run on production.
