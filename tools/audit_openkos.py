#!/usr/bin/env python3
"""Generate the repeatable OpenKos route-to-phase parity inventory."""

from __future__ import annotations

import argparse
import json
import subprocess
from collections import Counter
from pathlib import Path


PHASES = {
    0: "Parity specification and safe baseline",
    1: "Platform foundation and shared UI",
    2: "Identity, access, settings, and audit",
    3: "Properties, units, rates, media, and data transfer",
    4: "Tenants and leasing",
    5: "Billing, payments, PDFs, and gateways",
    6: "Maintenance, reminders, and notifications",
    7: "Expenses, dashboards, and reports",
    8: "Utilities and inspections",
    9: "Public listings and applications",
    10: "Tenant and applicant portal",
    11: "Integrations and extensions",
    12: "Data migration and cutover",
    13: "Stabilization and Laravel retirement",
}

EVIDENCE = {
    "shared application shell": ("core/urls.py; templates/base.html", "core/tests.py", "tools/browser_smoke.mjs"),
    "account security": ("accounts/urls.py; config/urls.py", "accounts/tests.py", "tools/completion_smoke.mjs"),
    "users, roles, and permissions": ("accounts/views.py; accounts/access.py", "accounts/tests.py", "tools/completion_smoke.mjs"),
    "settings and audit": ("accounts/audit.py; integrations/urls.py", "accounts/tests.py; integrations/tests.py", "tools/completion_smoke.mjs"),
    "property inventory": ("properties/urls.py", "properties/tests.py", "tools/phase3_smoke.mjs"),
    "CSV import/export": ("properties/urls.py; data_transfer/", "properties/tests.py; data_transfer/tests.py", "tools/phase3_smoke.mjs"),
    "tenants and tenant documents": ("properties/leasing_urls.py", "properties/test_phase4.py", "tools/phase4_smoke.mjs"),
    "leases and lifecycle actions": ("properties/leasing_urls.py", "properties/test_phase4.py", "tools/phase4_smoke.mjs"),
    "invoicing and rent schedules": ("billing/urls.py", "billing/tests.py", "tools/phase5_smoke.mjs"),
    "payments and proof review": ("billing/urls.py", "billing/tests.py", "tools/phase5_smoke.mjs"),
    "payment webhooks": ("billing/urls.py; billing/gateways.py", "billing/tests.py", "tools/completion_smoke.mjs"),
    "maintenance": ("operations/urls.py", "operations/tests.py", "tools/phase6_smoke.mjs"),
    "reminders and notification delivery": ("operations/services.py; integrations/services.py", "operations/tests.py; integrations/tests.py", "tools/phase6_smoke.mjs"),
    "expenses": ("operations/expense_urls.py", "operations/test_expenses.py", "tools/phase7_smoke.mjs"),
    "reporting dashboards": ("core/urls.py; operations/reports.py", "operations/test_expenses.py", "tools/phase7_smoke.mjs"),
    "utilities": ("operations/urls.py", "operations/test_utilities_inspections.py", "tools/phase8_smoke.mjs"),
    "inspections": ("operations/urls.py", "operations/test_utilities_inspections.py", "tools/phase8_smoke.mjs"),
    "public portal and applications": ("portal/urls.py; portal/staff_urls.py", "portal/test_phase9.py", "tools/phase9_smoke.mjs"),
    "tenant/applicant portal": ("portal/self_urls.py", "portal/test_phase10.py", "tools/phase10_smoke.mjs"),
    "plugins and extensions": ("integrations/registry.py; integrations/urls.py", "integrations/tests.py", "tools/phase11_smoke.mjs"),
}


def phase_for(route: dict[str, object]) -> tuple[int, str]:
    uri = str(route.get("uri", "")).strip("/")
    name = str(route.get("name") or "")
    action = str(route.get("action") or "")
    key = f"{uri} {name} {action}".lower()

    rules: list[tuple[int, str, tuple[str, ...]]] = [
        (5, "payment webhooks", ("api/webhooks/payment", "paymentwebhook")),
        (10, "tenant/applicant portal", ("tenant-portal", "tenantportal", "portal/")),
        (8, "inspections", ("inspection",)),
        (8, "utilities", ("utility", "meter", "reading")),
        (6, "maintenance", ("maintenance",)),
        (6, "reminders and notification delivery", ("reminder", "notification")),
        (7, "expenses", ("expense",)),
        (7, "reporting dashboards", ("dashboard", "report")),
        (5, "invoicing and rent schedules", ("invoice", "rent-schedule", "rentschedule")),
        (5, "payments and proof review", ("payment",)),
        (4, "tenants and tenant documents", ("tenant",)),
        (4, "leases and lifecycle actions", ("lease", "deposit-settlement", "move-out")),
        (3, "CSV import/export", ("data-transfer", "datatransfer")),
        (3, "property inventory", ("propert", "unit", "amenit")),
        (9, "public portal and applications", ("application", "public", "branding")),
        (11, "plugins and extensions", ("plugin",)),
        (2, "users, roles, and permissions", ("role", "permission", "users", "usercontroller")),
        (2, "account security", ("login", "logout", "password", "two-factor", "passkey", "verification", "register")),
        (2, "settings and audit", ("settings", "profile", "security", "audit", "activity")),
        (1, "shared application shell", ("storage/", "up", "health")),
    ]
    for phase, feature, needles in rules:
        if any(needle in key for needle in needles):
            return phase, feature
    return 1, "shared application shell"


def route_rows(openkos: Path) -> list[dict[str, object]]:
    result = subprocess.run(
        ["php", "artisan", "route:list", "--json"],
        cwd=openkos,
        check=True,
        capture_output=True,
        text=True,
    )
    routes = json.loads(result.stdout)
    rows: list[dict[str, object]] = []
    for route in routes:
        phase, feature = phase_for(route)
        rows.append({**route, "phase": phase, "feature": feature, "status": "planned"})
    return rows


def route_key(route: dict[str, object]) -> tuple[str, str, str]:
    return (
        str(route.get("method") or ""),
        str(route.get("uri") or ""),
        str(route.get("name") or ""),
    )


def markdown(rows: list[dict[str, object]]) -> str:
    counts = Counter(int(row["phase"]) for row in rows)
    lines = [
        "# OpenKos Route Parity Matrix",
        "",
        "This file is generated by `tools/audit_openkos.py`. It assigns every",
        "Laravel route to a Django implementation and executable evidence.",
        "A verified row has server-side tests plus a browser workflow covering its feature group.",
        "",
        f"**Source routes:** {len(rows)}",
        "",
        "## Phase coverage",
        "",
        "| Phase | Scope | Routes |",
        "| ---: | --- | ---: |",
    ]
    for phase, title in PHASES.items():
        lines.append(f"| {phase} | {title} | {counts.get(phase, 0)} |")
    lines.extend(
        [
            "",
            "## Route assignments",
            "",
            "| Phase | Method | Laravel URI | Route name | Feature | Django replacement | Automated evidence | Browser evidence | Status |",
            "| ---: | --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for row in rows:
        uri = str(row.get("uri") or "").replace("|", "\\|")
        name = str(row.get("name") or "—").replace("|", "\\|")
        method = str(row.get("method") or "").replace("|", ", ")
        implementation, tests, browser = EVIDENCE[str(row["feature"])]
        lines.append(
            f"| {row['phase']} | {method} | `{uri}` | `{name}` | "
            f"{row['feature']} | `{implementation}` | `{tests}` | `{browser}` | {row['status']} |"
        )
    lines.extend(
        [
            "",
            "## Completion rule",
            "",
            "A phase is complete only after its routes have equivalent Django",
            "behavior, permission checks, validation, tests, and browser verification.",
            "Framework-only routes require a written reason in the implementation PR.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--openkos", type=Path, default=Path("/home/hamed/OpenKos"))
    parser.add_argument("--output", type=Path, default=Path("docs/PARITY_MATRIX.md"))
    parser.add_argument("--json", type=Path, default=Path("docs/openkos-routes.json"))
    parser.add_argument("--complete-phase", type=int, action="append", default=[])
    parser.add_argument("--from-json", action="store_true", help="Regenerate from the checked-in source route inventory.")
    args = parser.parse_args()

    rows = json.loads(args.json.read_text(encoding="utf-8")) if args.from_json else route_rows(args.openkos.resolve())
    if args.json.exists():
        previous = {
            route_key(row): str(row.get("status", "planned"))
            for row in json.loads(args.json.read_text(encoding="utf-8"))
        }
        for row in rows:
            row["status"] = previous.get(route_key(row), "planned")
    for row in rows:
        if int(row["phase"]) in args.complete_phase:
            row["status"] = "verified"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(markdown(rows), encoding="utf-8")
    args.json.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    print(f"Mapped {len(rows)} routes to {args.output} and {args.json}")


if __name__ == "__main__":
    main()
