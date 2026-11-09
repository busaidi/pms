# Phase 12 migration reconciliation

Completed 29 September 2026 from source fingerprint
`899d05e30f02837b7321fb5b68f245699313e1e8b8931a5700a63d1a232f94ce`.

Two clean PostgreSQL rehearsals restored the same Laravel custom-format backup.
Each created 1,522 mappings with zero count differences. A repeat of rehearsal
one created zero rows and reused all 1,522 mappings. The production run created
1,454 targets, reused 68 safe natural-key matches from the Django demo dataset,
and mapped all 1,522 source rows.

| Domain | Source | Mapped | Difference |
| --- | ---: | ---: | ---: |
| Users | 4 | 4 | 0 |
| Roles / permissions | 64 | 64 | 0 |
| Settings | 10 | 10 | 0 |
| Regions / cities | 551 | 551 | 0 |
| Property types / amenities | 20 | 20 | 0 |
| Properties / unit types / units | 133 | 133 | 0 |
| Unit rates | 280 | 280 | 0 |
| Tenants / leases | 39 | 39 | 0 |
| Invoices / line items | 108 | 108 | 0 |
| Payments / allocations | 17 | 17 | 0 |
| Expense categories | 8 | 8 | 0 |
| Maintenance tickets | 3 | 3 | 0 |
| Notifications / reminder logs | 158 | 158 | 0 |
| Activity / audit logs | 127 | 127 | 0 |

Empty source domains also reconcile at zero: property and unit-type rates,
expenses and recurring expenses, utilities, inspections, applications, payment
attempts/proofs, deposit settlements, lease histories, and media/documents.

| Financial/occupancy check | Source | Django | Difference |
| --- | ---: | ---: | ---: |
| Invoice total | OMR 75,603,050.000 | OMR 75,603,050.000 | OMR 0.000 |
| Payment total | OMR 10,050,850.000 | OMR 10,050,850.000 | OMR 0.000 |
| Active leases | 11 | 11 | 0 |

Post-cutover checks found zero unit/lease property mismatches. All 104 automated
tests pass. Staff, public listing, resident portal, billing/PDF, maintenance,
reminder, expenses, utilities, inspections, applications, integrations, mobile,
and desktop browser journeys pass. Laravel still returns HTTP 200 locally.

Machine-readable reports are retained outside Git under `artifacts/` and the
signed backup checksums are retained under `backups/`.
