# Expiry alerts and handover

- Operator pages show a live, property-permission-scoped alert for active leases ending within 30 days, including overdue leases. The list offers 30/60/90-day windows. These alerts require no worker, email, or external integration.
- A lease's final rental day is inclusive. A one-day lease shows "ends today" on that date, and "expired — awaiting action" the next local day (Asia/Muscat).
- Awaiting action is computed from the end date; the stored active state keeps occupancy blocked. The operator renews or confirms actual handover. No automatic termination occurs.
- Termination, move-out and unit transfer require explicit handover confirmation at the service layer. Future handovers cannot release inventory. A move confirms handover of the old unit.
- Migration 0014 records handover timestamp and operator. Move-out date is separate from the original contractual end date. Issued invoices and outstanding balances remain unchanged. Deposit settlement is optional and atomic with move-out when requested together.
- Maintenance/unavailable units retain their blocked state after handover. Public offers also check open occupancy, including whole-property leases.
- Existing historical terminated contracts are not backfilled with invented handover confirmations.

Validation: `manage.py test properties.test_lease_handover properties.lease_tests --settings=config.settings.postgres_test --noinput`.
