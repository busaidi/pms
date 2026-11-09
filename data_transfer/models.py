from django.db import models


class MigrationRun(models.Model):
    class Status(models.TextChoices):
        RUNNING = "running", "Running"
        COMPLETE = "complete", "Complete"
        REHEARSAL = "rehearsal", "Dry-run rehearsal"
        FAILED = "failed", "Failed"

    source = models.CharField(max_length=80, default="openkos")
    source_fingerprint = models.CharField(max_length=64)
    domains = models.JSONField(default=list)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.RUNNING)
    summary = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-started_at",)


class LegacyRecordMap(models.Model):
    source = models.CharField(max_length=80, default="openkos")
    source_table = models.CharField(max_length=120)
    source_id = models.CharField(max_length=120)
    target_model = models.CharField(max_length=120)
    target_id = models.CharField(max_length=120)
    checksum = models.CharField(max_length=64, blank=True)
    migrated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("source", "source_table", "source_id"), name="unique_legacy_source_record")]
        indexes = [models.Index(fields=("target_model", "target_id"))]
