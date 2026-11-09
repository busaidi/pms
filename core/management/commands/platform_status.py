import json
import shutil

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection
from django.utils import timezone
from redis import Redis

from billing.models import PaymentAnomaly, PaymentAttempt
from integrations.models import ExtensionInstallation
from operations.models import ReminderLog


class Command(BaseCommand):
    help = "Report database, queue, payment, delivery, extension, and storage health as JSON"

    def add_arguments(self, parser):
        parser.add_argument("--fail-on-degraded", action="store_true")

    def handle(self, *args, **options):
        status = "ok"
        report = {"checked_at": timezone.now().isoformat(), "checks": {}}
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_database_size(current_database()), numbackends, "
                "deadlocks, temp_bytes FROM pg_stat_database "
                "WHERE datname=current_database()"
            )
            size, connections, deadlocks, temp_bytes = cursor.fetchone()
            cursor.execute(
                "SELECT count(*) FROM pg_stat_activity "
                "WHERE datname=current_database() AND state='active' "
                "AND query_start < now() - interval '5 seconds'"
            )
            slow_active = cursor.fetchone()[0]
        report["checks"]["database"] = {
            "status": "degraded" if slow_active or deadlocks else "ok",
            "size_bytes": size,
            "connections": connections,
            "deadlocks": deadlocks,
            "temp_bytes": temp_bytes,
            "queries_active_over_5s": slow_active,
        }
        try:
            queue_ok = bool(Redis.from_url(settings.CELERY_BROKER_URL, socket_timeout=1).ping())
        except Exception:
            queue_ok = False
        report["checks"]["queue"] = {"status": "ok" if queue_ok else "critical"}
        pending_cutoff = timezone.now() - timezone.timedelta(hours=24)
        stale_attempts = PaymentAttempt.objects.filter(
            status=PaymentAttempt.Status.PENDING,
            created_at__lt=pending_cutoff,
        ).count()
        anomalies = PaymentAnomaly.objects.count()
        report["checks"]["payments"] = {
            "status": "degraded" if stale_attempts or anomalies else "ok",
            "anomalies": anomalies,
            "pending_over_24h": stale_attempts,
        }
        failed_deliveries = ReminderLog.objects.filter(
            status="failed",
            created_at__gte=timezone.now() - timezone.timedelta(days=1),
        ).count()
        report["checks"]["delivery"] = {
            "status": "degraded" if failed_deliveries else "ok",
            "failures_last_24h": failed_deliveries,
        }
        degraded_extensions = ExtensionInstallation.objects.exclude(
            status__in=(
                ExtensionInstallation.Status.READY,
                ExtensionInstallation.Status.DISABLED,
            )
        ).count()
        report["checks"]["extensions"] = {
            "status": "degraded" if degraded_extensions else "ok",
            "degraded": degraded_extensions,
        }
        disk = shutil.disk_usage(settings.MEDIA_ROOT)
        free_ratio = disk.free / disk.total if disk.total else 0
        storage_status = (
            "critical" if free_ratio < 0.1 else "degraded" if free_ratio < 0.2 else "ok"
        )
        report["checks"]["storage"] = {
            "status": storage_status,
            "total_bytes": disk.total,
            "used_bytes": disk.used,
            "free_bytes": disk.free,
        }
        levels = [item["status"] for item in report["checks"].values()]
        if "critical" in levels:
            status = "critical"
        elif "degraded" in levels:
            status = "degraded"
        report["status"] = status
        self.stdout.write(json.dumps(report, sort_keys=True))
        if options["fail_on_degraded"] and status != "ok":
            raise SystemExit(1)
