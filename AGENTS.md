# Repository Guidelines

## Project Structure & Module Organization

This is a Django 5.2 property-management application. Configuration lives in `config/`; `manage.py` is the command entry point. Business domains are split into `accounts/`, `billing/`, `core/`, `data_transfer/`, `integrations/`, `operations/`, `portal/`, and `properties/`. Keep logic in the relevant app, favoring service or selector modules over large views.

Templates are grouped by app under `templates/`. Browser assets live in `static/`; generated `staticfiles/` is not source. Arabic translations are under `locale/ar/`. Scripts are in `tools/`, deployment definitions in `deployment/`, and documentation in `docs/`.

## Build, Test, and Development Commands

Create and activate a virtual environment, then install dependencies with `pip install -r requirements.txt`. Use:

- `python manage.py runserver 127.0.0.1:8000` — start the local server.
- `python manage.py check` — validate Django configuration and models.
- `python manage.py test` — run the default SQLite-backed test suite.
- `npm ci` — install pinned browser-test dependencies.
- `npm run test:browser` — run Playwright smoke coverage; `test:accessibility` and `test:arabic` cover those focused flows.
- `tools/verify_completion.sh` — run the full PostgreSQL, localization, and deployment-readiness verification used for completion checks.

## Coding Style & Naming Conventions

Follow standard Python conventions: four-space indentation, `snake_case` functions and modules, `PascalCase` classes, and uppercase constants. Use descriptive Django model, form, URL, and template names. Keep migrations generated and ordered inside each app’s `migrations/` directory; do not hand-edit historical migrations without a specific reason. Match surrounding template and JavaScript style. No repository-wide formatter is configured, so keep diffs focused and imports organized.

## Testing Guidelines

Tests use Django’s `TestCase` and are colocated in app-level `tests.py` or `test_*.py` files. Name test classes by behavior and methods `test_<expected_behavior>`. Add regression tests with every bug fix, especially for permissions, money calculations (OMR uses three decimal places), lease state changes, and audit records. Run the narrow app test first, for example `python manage.py test operations.test_expenses`, then the full suite.

## Commit & Pull Request Guidelines

History uses Conventional Commit prefixes such as `feat:` and `fix:` with imperative summaries. Keep each commit scoped. Pull requests should explain the user-visible effect, list validation commands, link the relevant issue or parity phase, and include screenshots for template, responsive, or localization changes. Call out migrations, configuration, and deployment impact.

## Security & Configuration

Before production deployment, read and follow `deployment/CODEX_DEPLOY.md`. Contract configuration transfers use the add-only `export_contract_config` / `import_contract_config` commands; never restore the local production backup over the live database. By explicit owner authorization, `artifacts/deployment/production.contract-bundle.json` and its `production.sha256.txt` are committed for deployment. Other private transfer bundles and artifacts remain excluded. Do not serve the committed bundle publicly or print its contents.

Never commit `.env`, `.secret_key`, credentials, database dumps, `media/`, or generated artifacts. Configure production through `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, and `DJANGO_ALLOWED_HOSTS`, and preserve existing property-scoped authorization and immutable audit behavior.
