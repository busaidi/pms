from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import Inspection, InspectionItem, InspectionPhoto
from django.utils.translation import gettext_lazy as _


@transaction.atomic
def create_inspection(*, template, property_obj, unit=None, lease=None, inspection_date, inspector, notes=""):
    if template.inspection_type in {template.Type.MOVE_IN, template.Type.MOVE_OUT} and lease is None:
        raise ValidationError(_("Move-in and move-out inspections must be linked to a lease."))
    if unit and unit.property_id != property_obj.pk: raise ValidationError(_("The unit does not belong to this property."))
    if lease and lease.property_id != property_obj.pk: raise ValidationError(_("The lease does not belong to this property."))
    inspection = Inspection.objects.create(template=template, template_name=template.name, property=property_obj, unit=unit or (lease.unit if lease else None), lease=lease, inspection_type=template.inspection_type, inspection_date=inspection_date, inspector=inspector, scheduled_for=timezone.now(), status=Inspection.Status.DRAFT, notes=notes)
    InspectionItem.objects.bulk_create([InspectionItem(inspection=inspection, label=item.label, description=item.guidance, sort_order=item.sort_order) for item in template.items.all()])
    return inspection


@transaction.atomic
def update_inspection(inspection, *, actor, notes="", damage_observations="", items=None):
    inspection = Inspection.objects.select_for_update().get(pk=inspection.pk)
    if inspection.status == Inspection.Status.COMPLETED: raise ValidationError(_("Completed inspections are immutable."))
    inspection.notes = notes; inspection.damage_observations = damage_observations; inspection.save(update_fields=("notes", "damage_observations"))
    item_map = {item.pk: item for item in inspection.items.all()}
    for row in items or []:
        item = item_map.get(int(row["id"]))
        if not item: raise ValidationError(_("Inspection item does not belong to this inspection."))
        item.condition = row.get("condition", ""); item.notes = row.get("notes", ""); item.save(update_fields=("condition", "notes"))
    return inspection


@transaction.atomic
def complete_inspection(inspection, *, actor):
    inspection = Inspection.objects.select_for_update().get(pk=inspection.pk)
    if inspection.status == Inspection.Status.COMPLETED: return inspection
    if inspection.items.filter(condition="").exists(): raise ValidationError(_("Assess every checklist item before completion."))
    inspection.status = Inspection.Status.COMPLETED; inspection.completed_by = actor; inspection.completed_at = timezone.now(); inspection.save(update_fields=("status", "completed_by", "completed_at")); return inspection


def add_inspection_photo(item, upload, caption=""):
    if item.inspection.status == Inspection.Status.COMPLETED: raise ValidationError(_("Completed inspections are immutable."))
    photo = InspectionPhoto(item=item, file=upload, caption=caption, original_name=upload.name, mime_type=getattr(upload, "content_type", ""), size=upload.size)
    photo.full_clean(); photo.save(); return photo
