import json
from pathlib import Path

import psycopg
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from billing.models import Invoice, Payment
from data_transfer.models import LegacyRecordMap, MigrationRun
from data_transfer.openkos import OpenKosImporter, SOURCE, SourceDatabase
from properties.models import Lease


class Command(BaseCommand):
    help = "Idempotently migrate the read-only OpenKos PostgreSQL database into Django"

    def add_arguments(self, parser):
        parser.add_argument("--source-dsn-file", required=True, type=Path)
        parser.add_argument("--domains", help="Comma-separated migration domains; defaults to all")
        parser.add_argument("--dry-run", action="store_true", help="Execute the full import and roll target writes back")
        parser.add_argument("--reconcile-only", action="store_true")
        parser.add_argument("--report", type=Path)

    def handle(self, *args, **options):
        dsn_file = options["source_dsn_file"]
        if not dsn_file.is_file():
            raise CommandError("Source DSN file does not exist.")
        dsn = dsn_file.read_text(encoding="utf-8").strip()
        if not dsn:
            raise CommandError("Source DSN file is empty.")
        domains = [item.strip() for item in options["domains"].split(",") if item.strip()] if options.get("domains") else list(OpenKosImporter.domains)
        connection = psycopg.connect(dsn)
        try:
            connection.execute("SET default_transaction_read_only = on")
            source = SourceDatabase(connection)
            fingerprint, source_counts = source.fingerprint()
            run = MigrationRun.objects.create(source=SOURCE, source_fingerprint=fingerprint, domains=domains)
            importer = OpenKosImporter(source, self.stdout.write)
            try:
                with transaction.atomic():
                    summary = {"source_counts": source_counts}
                    if not options["reconcile_only"]:
                        summary = importer.run(domains)
                    reconciliation = importer.reconciliation()
                    financials = self._financial_reconciliation(source)
                    summary["reconciliation"] = reconciliation
                    summary["financials"] = financials
                    if options["dry_run"]:
                        transaction.set_rollback(True)
                run.status = MigrationRun.Status.REHEARSAL if options["dry_run"] else MigrationRun.Status.COMPLETE
                run.summary = summary
                run.completed_at = timezone.now()
                run.save(update_fields=("status", "summary", "completed_at"))
            except Exception as error:
                run.status = MigrationRun.Status.FAILED
                run.error_message = str(error)
                run.completed_at = timezone.now()
                run.save(update_fields=("status", "error_message", "completed_at"))
                raise
            report = {"run_id": run.pk, "status": run.status, "source_fingerprint": fingerprint, "domains": domains, **summary}
            if options.get("report"):
                options["report"].parent.mkdir(parents=True, exist_ok=True)
                options["report"].write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
            differences = sum(abs(item["difference"]) for item in reconciliation.values())
            self.stdout.write(self.style.SUCCESS(f"OpenKos migration {run.status}: {len(LegacyRecordMap.objects.filter(source=SOURCE))} mapped records; {differences} count difference(s)."))
        finally:
            connection.close()

    def _financial_reconciliation(self, source):
        invoice_ids = list(LegacyRecordMap.objects.filter(source=SOURCE, source_table="invoices", target_model="billing.Invoice").values_list("target_id", flat=True))
        payment_ids = list(LegacyRecordMap.objects.filter(source=SOURCE, source_table="payments", target_model="billing.Payment").values_list("target_id", flat=True))
        lease_ids = list(LegacyRecordMap.objects.filter(source=SOURCE, source_table="leases", target_model="properties.Lease").values_list("target_id", flat=True))
        source_invoice_total = source.scalar("SELECT COALESCE(sum(total), 0) FROM invoices") if source.table_exists("invoices") else 0
        source_payment_total = source.scalar("SELECT COALESCE(sum(amount), 0) FROM payments") if source.table_exists("payments") else 0
        source_active_leases = source.scalar("SELECT count(*) FROM leases WHERE status = 'active'") if source.table_exists("leases") else 0
        target_invoice_total = Invoice.objects.filter(pk__in=invoice_ids).aggregate(value=Sum("total"))["value"] or 0
        target_payment_total = Payment.objects.filter(pk__in=payment_ids).aggregate(value=Sum("amount"))["value"] or 0
        target_active_leases = Lease.objects.filter(pk__in=lease_ids, status=Lease.Status.ACTIVE).count()
        return {
            "invoice_total": {"source": str(source_invoice_total), "target": str(target_invoice_total), "difference": str(source_invoice_total - target_invoice_total)},
            "payment_total": {"source": str(source_payment_total), "target": str(target_payment_total), "difference": str(source_payment_total - target_payment_total)},
            "active_leases": {"source": source_active_leases, "target": target_active_leases, "difference": source_active_leases - target_active_leases},
        }
