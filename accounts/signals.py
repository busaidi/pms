from django.contrib.auth import get_user_model
from django.db.models.signals import post_delete, post_save, pre_delete, pre_save
from django.dispatch import receiver

from .audit import current, snapshot
from .models import AuditLog, UserProfile


@receiver(post_save, sender=get_user_model())
def ensure_user_profile(sender, instance, created, **kwargs):
    UserProfile.objects.get_or_create(user=instance)


AUDITED_APPS = {"auth", "accounts", "properties", "billing", "operations", "integrations", "portal"}


def _should_audit(sender):
    return current() and sender is not AuditLog and sender._meta.app_label in AUDITED_APPS


@receiver(pre_save)
def capture_before_save(sender, instance, raw=False, **kwargs):
    if raw or not _should_audit(sender) or not instance.pk:
        return
    before = sender._default_manager.filter(pk=instance.pk).first()
    instance._audit_before = snapshot(before) if before else None


@receiver(post_save)
def audit_model_save(sender, instance, created=False, raw=False, **kwargs):
    context = current()
    if raw or not _should_audit(sender):
        return
    before = getattr(instance, "_audit_before", None)
    after = snapshot(instance)
    if not created and before == after:
        return
    action = "created" if created else "updated"
    AuditLog.objects.create(
        actor_id=context["actor_id"], action=f"{sender._meta.label_lower}.{action}",
        target_type=sender._meta.label, target_id=str(instance.pk),
        summary=f"{action.title()} {sender._meta.verbose_name} {instance}"[:255],
        changes={"before": before, "after": after}, ip_address=context["ip_address"],
    )


@receiver(pre_delete)
def capture_before_delete(sender, instance, **kwargs):
    if _should_audit(sender):
        instance._audit_before = snapshot(instance)


@receiver(post_delete)
def audit_model_delete(sender, instance, **kwargs):
    context = current()
    if not _should_audit(sender):
        return
    AuditLog.objects.create(
        actor_id=context["actor_id"], action=f"{sender._meta.label_lower}.deleted",
        target_type=sender._meta.label, target_id=str(instance.pk),
        summary=f"Deleted {sender._meta.verbose_name} {instance}"[:255],
        changes={"before": getattr(instance, "_audit_before", snapshot(instance)), "after": None},
        ip_address=context["ip_address"],
    )
