import secrets

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.access import properties_for_user, user_has_capability
from .forms import AmenityForm, MediaForm, PropertyForm, PropertyRateForm, PropertyTypeForm, UnitForm, UnitRateForm, UnitTypeForm, UnitTypeRateForm
from .models import Amenity, Property, PropertyMedia, PropertyRate, PropertyType, Unit, UnitRate, UnitTypeRate
from .services import effective_unit_rates, publication_readiness
from .transfers import DATASETS, csv_response_rows, export_rows, parse_csv, template_csv, validate_rows
from django.utils.translation import gettext_lazy as _


def _property(request, slug, capability="properties.view", include_archived=True):
    queryset = properties_for_user(request.user, capability)
    if not include_archived:
        queryset = queryset.filter(archived_at__isnull=True)
    return get_object_or_404(queryset, slug=slug)


@login_required
def property_list(request):
    if not user_has_capability(request.user, "properties.view"):
        raise PermissionDenied
    items = properties_for_user(request.user).select_related("property_type", "region_ref", "city_ref")
    archived = request.GET.get("status") == "archived"
    items = items.filter(archived_at__isnull=not archived)
    search = request.GET.get("q", "").strip()
    if search:
        items = items.filter(name__icontains=search)
    return render(request, "properties/property_list.html", {"properties": items, "archived": archived, "search": search})


@login_required
def property_create(request):
    if not user_has_capability(request.user, "properties.create"):
        raise PermissionDenied
    form = PropertyForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        obj = form.save()
        messages.success(request, _("Property created."))
        return redirect("property_workspace", slug=obj.slug)
    return render(request, "properties/form.html", {"form": form, "title": "Add property", "eyebrow": "Inventory"})


@login_required
def master_data(request):
    if not user_has_capability(request.user, "properties.update"): raise PermissionDenied
    return render(request, "properties/master_data.html", {"property_types": PropertyType.objects.all(), "amenities": Amenity.objects.all(), "property_type_form": PropertyTypeForm(), "amenity_form": AmenityForm()})


@login_required
@require_POST
def property_type_save(request, type_id=None):
    if not user_has_capability(request.user, "properties.update"): raise PermissionDenied
    instance = get_object_or_404(PropertyType, pk=type_id) if type_id else None; form = PropertyTypeForm(request.POST, instance=instance)
    if form.is_valid(): form.save(); messages.success(request, _("Property type saved."))
    else: messages.error(request, _("Property type could not be saved: ") + " ".join(sum(form.errors.values(), [])))
    return redirect("inventory_master_data")


@login_required
@require_POST
def amenity_save(request, amenity_id=None):
    if not user_has_capability(request.user, "properties.update"): raise PermissionDenied
    instance = get_object_or_404(Amenity, pk=amenity_id) if amenity_id else None; form = AmenityForm(request.POST, instance=instance)
    if form.is_valid(): form.save(); messages.success(request, _("Amenity saved."))
    else: messages.error(request, _("Amenity could not be saved: ") + " ".join(sum(form.errors.values(), [])))
    return redirect("inventory_master_data")


@login_required
@require_POST
def amenity_delete(request, amenity_id):
    if not user_has_capability(request.user, "properties.update"): raise PermissionDenied
    amenity = get_object_or_404(Amenity, pk=amenity_id)
    if amenity.properties.exists() or amenity.unit_types.exists(): messages.error(request, _("Remove this amenity from inventory before deleting it."))
    else: amenity.delete(); messages.success(request, _("Amenity deleted."))
    return redirect("inventory_master_data")


@login_required
def property_edit(request, slug):
    obj = _property(request, slug, "properties.update")
    old_mode = obj.rental_mode
    form = PropertyForm(request.POST or None, instance=obj)
    if request.method == "POST" and form.is_valid():
        if obj.is_published and form.cleaned_data["rental_mode"] != old_mode:
            form.add_error("rental_mode", _("Unpublish the property before changing its rental model."))
        else:
            obj = form.save()
            messages.success(request, _("Property updated."))
            return redirect("property_workspace", slug=obj.slug)
    return render(request, "properties/form.html", {"form": form, "title": f"Edit {obj.name}", "eyebrow": "Property workspace", "property": obj})


@login_required
def property_workspace(request, slug):
    obj = _property(request, slug)
    show_archived_units = request.GET.get("show") == "archived"
    units = obj.units.filter(archived_at__isnull=not show_archived_units).select_related("unit_type")
    show_archived_types = request.GET.get("types") == "archived"
    unit_types = obj.unit_types.filter(archived_at__isnull=not show_archived_types).prefetch_related("rates")
    return render(request, "properties/workspace.html", {
        "property": obj, "units": [{"unit": unit, "rates": effective_unit_rates(unit), "own_rates": unit.rates.all()} for unit in units],
        "unit_types": unit_types,
        "property_rates": obj.rates.all(), "media_items": obj.media.select_related("unit_type"),
        "readiness": publication_readiness(obj), "tab": request.GET.get("tab", "overview"),
        "show_archived_units": show_archived_units,
        "show_archived_types": show_archived_types,
        "unit_form": UnitForm(property_obj=obj), "unit_type_form": UnitTypeForm(),
        "property_rate_form": PropertyRateForm(), "media_form": MediaForm(property_obj=obj),
    })


@login_required
@require_POST
def property_archive(request, slug):
    obj = _property(request, slug, "properties.delete")
    try:
        obj.archive(); messages.success(request, _("Property archived. Its history remains available."))
    except ValidationError as error:
        messages.error(request, error.messages[0])
    return redirect("property_workspace", slug=obj.slug)


@login_required
@require_POST
def property_restore(request, slug):
    obj = _property(request, slug, "properties.delete"); obj.restore()
    messages.success(request, _("Property restored."))
    return redirect("property_workspace", slug=obj.slug)


@login_required
@require_POST
def property_publish(request, slug):
    obj = _property(request, slug, "properties.update"); readiness = publication_readiness(obj)
    if not readiness["ready"]:
        messages.error(request, _("Cannot publish: ") + " ".join(readiness["problems"]))
    else:
        obj.is_public = obj.is_published = True; obj.save(update_fields=("is_public", "is_published", "updated_at"))
        messages.success(request, _("Property is now published."))
    return redirect("property_workspace", slug=obj.slug)


@login_required
@require_POST
def property_unpublish(request, slug):
    obj = _property(request, slug, "properties.update"); obj.is_public = obj.is_published = False
    obj.save(update_fields=("is_public", "is_published", "updated_at")); messages.success(request, _("Property unpublished."))
    return redirect("property_workspace", slug=obj.slug)


@login_required
@require_POST
def unit_create(request, slug):
    obj = _property(request, slug, "units.create", False)
    if not obj.supports_unit_inventory:
        messages.error(request, _("Whole-property inventory cannot contain rentable units."))
    else:
        form = UnitForm(request.POST, property_obj=obj)
        if form.is_valid():
            unit = form.save(commit=False); unit.property = obj
            try:
                unit.full_clean(); unit.save(); messages.success(request, _("Unit %(unit)s added.") % {"unit": unit.name})
            except ValidationError as error: messages.error(request, _("Unit could not be added: ") + " ".join(error.messages))
        else:
            messages.error(request, _("Unit could not be added: ") + " ".join(sum(form.errors.values(), [])))
    return redirect(f"/properties/{obj.slug}/?tab=units")


@login_required
def unit_edit(request, slug, unit_id):
    obj = _property(request, slug, "units.update", False); unit = get_object_or_404(obj.units, pk=unit_id)
    form = UnitForm(request.POST or None, instance=unit, property_obj=obj)
    if request.method == "POST" and form.is_valid():
        form.save(); messages.success(request, _("Unit updated.")); return redirect(f"/properties/{obj.slug}/?tab=units")
    return render(request, "properties/form.html", {"form": form, "title": f"Edit unit {unit.name}", "eyebrow": obj.name, "property": obj})


@login_required
@require_POST
def unit_archive(request, slug, unit_id):
    from django.utils import timezone
    obj = _property(request, slug, "units.delete"); unit = get_object_or_404(obj.units, pk=unit_id)
    if unit.leases.filter(status__in=("active", "pending", "notice")).exists():
        messages.error(request, _("A unit with a current lease cannot be archived."))
    else:
        unit.archived_at = timezone.now(); unit.status = Unit.Status.UNAVAILABLE
        unit.save(update_fields=("archived_at", "status", "updated_at")); messages.success(request, _("Unit archived."))
    return redirect(f"/properties/{obj.slug}/?tab=units")


@login_required
@require_POST
def unit_restore(request, slug, unit_id):
    obj = _property(request, slug, "units.delete"); unit = get_object_or_404(obj.units, pk=unit_id)
    unit.archived_at = None; unit.status = Unit.Status.AVAILABLE
    unit.save(update_fields=("archived_at", "status", "updated_at")); messages.success(request, _("Unit restored."))
    return redirect(f"/properties/{obj.slug}/?tab=units&show=archived")


@login_required
@require_POST
def units_bulk_assign(request, slug):
    obj = _property(request, slug, "units.update")
    unit_type = get_object_or_404(obj.unit_types, pk=request.POST.get("unit_type"), archived_at__isnull=True)
    count = obj.units.filter(pk__in=request.POST.getlist("units"), archived_at__isnull=True).update(unit_type=unit_type)
    messages.success(request, _("Assigned %(count)s units to %(unit_type)s.") % {"count": count, "unit_type": unit_type.name})
    return redirect(f"/properties/{obj.slug}/?tab=units")


@login_required
@require_POST
def unit_type_create(request, slug):
    obj = _property(request, slug, "units.create", False); form = UnitTypeForm(request.POST)
    if form.is_valid():
        value = form.save(commit=False); value.property = obj
        try:
            value.full_clean(); value.save(); form.save_m2m(); messages.success(request, _("Unit type added."))
        except ValidationError as error: messages.error(request, _("Unit type could not be added: ") + " ".join(error.messages))
    else: messages.error(request, _("Unit type could not be added: ") + " ".join(sum(form.errors.values(), [])))
    return redirect(f"/properties/{obj.slug}/?tab=types")


@login_required
def unit_type_edit(request, slug, type_id):
    obj = _property(request, slug, "units.update"); unit_type = get_object_or_404(obj.unit_types, pk=type_id)
    form = UnitTypeForm(request.POST or None, instance=unit_type)
    if request.method == "POST" and form.is_valid():
        form.save(); messages.success(request, _("Unit type updated.")); return redirect(f"/properties/{obj.slug}/?tab=types")
    return render(request, "properties/form.html", {"form": form, "title": f"Edit {unit_type.name}", "eyebrow": obj.name, "property": obj})


@login_required
@require_POST
def unit_type_archive(request, slug, type_id):
    from django.utils import timezone
    obj = _property(request, slug, "units.delete"); unit_type = get_object_or_404(obj.unit_types, pk=type_id)
    if unit_type.units.filter(archived_at__isnull=True).exists():
        messages.error(request, _("Reassign active units before archiving this unit type."))
    else:
        unit_type.archived_at = timezone.now(); unit_type.is_active = unit_type.is_published = False
        unit_type.save(update_fields=("archived_at", "is_active", "is_published")); messages.success(request, _("Unit type archived."))
    return redirect(f"/properties/{obj.slug}/?tab=types")


@login_required
@require_POST
def unit_type_restore(request, slug, type_id):
    obj = _property(request, slug, "units.delete"); unit_type = get_object_or_404(obj.unit_types, pk=type_id)
    unit_type.archived_at = None; unit_type.is_active = True
    unit_type.save(update_fields=("archived_at", "is_active")); messages.success(request, _("Unit type restored."))
    return redirect(f"/properties/{obj.slug}/?tab=types&types=archived")


def _save_rate(request, obj, form_class, relation, success):
    form = form_class(request.POST)
    if form.is_valid():
        value = form.save(commit=False); setattr(value, relation, obj)
        try:
            value.full_clean(); value.save(); messages.success(request, success)
        except ValidationError as error: messages.error(request, _("Rate could not be added: ") + " ".join(error.messages))
    else: messages.error(request, _("Rate could not be added: ") + " ".join(sum(form.errors.values(), [])))


@login_required
@require_POST
def property_rate_create(request, slug):
    obj = _property(request, slug, "properties.update", False)
    if obj.supports_property_pricing: _save_rate(request, obj, PropertyRateForm, "property", "Property rate added.")
    else: messages.error(request, _("This rental mode does not support whole-property pricing."))
    return redirect(f"/properties/{obj.slug}/?tab=pricing")


@login_required
@require_POST
def unit_rate_create(request, slug, unit_id):
    obj = _property(request, slug, "units.update", False); unit = get_object_or_404(obj.units, pk=unit_id, archived_at__isnull=True)
    _save_rate(request, unit, UnitRateForm, "unit", f"Rate added to unit {unit.name}.")
    return redirect(f"/properties/{obj.slug}/?tab=pricing")


@login_required
@require_POST
def unit_type_rate_create(request, slug, type_id):
    obj = _property(request, slug, "units.update", False); unit_type = get_object_or_404(obj.unit_types, pk=type_id, archived_at__isnull=True)
    _save_rate(request, unit_type, UnitTypeRateForm, "unit_type", f"Rate added to {unit_type.name}.")
    return redirect(f"/properties/{obj.slug}/?tab=pricing")


@login_required
@require_POST
def rate_toggle(request, slug, kind, rate_id):
    obj = _property(request, slug, "properties.update")
    models = {"property": (PropertyRate, {"property": obj}), "type": (UnitTypeRate, {"unit_type__property": obj}), "unit": (UnitRate, {"unit__property": obj})}
    if kind not in models: raise Http404
    model, filters = models[kind]; rate = get_object_or_404(model, pk=rate_id, **filters)
    rate.is_active = not rate.is_active; rate.save(update_fields=("is_active", "updated_at"))
    messages.success(request, _("Rate %(status)s.") % {"status": _("activated") if rate.is_active else _("deactivated")})
    return redirect(f"/properties/{obj.slug}/?tab=pricing")


@login_required
@require_POST
def media_upload(request, slug):
    obj = _property(request, slug, "properties.update", False); form = MediaForm(request.POST, request.FILES, property_obj=obj)
    if form.is_valid():
        media = form.save(commit=False); media.property = obj; media.full_clean(); media.save(); messages.success(request, _("Media uploaded."))
    else: messages.error(request, _("Upload failed: ") + " ".join(sum(form.errors.values(), [])))
    return redirect(f"/properties/{obj.slug}/?tab=media")


@login_required
def media_edit(request, slug, media_id):
    obj = _property(request, slug, "properties.update"); media = get_object_or_404(obj.media, pk=media_id)
    form = MediaForm(request.POST or None, request.FILES or None, instance=media, property_obj=obj)
    if request.method == "POST" and form.is_valid():
        form.save(); messages.success(request, _("Media metadata updated.")); return redirect(f"/properties/{obj.slug}/?tab=media")
    return render(request, "properties/form.html", {"form": form, "title": "Edit media", "eyebrow": obj.name, "property": obj})


@login_required
@require_POST
def media_move(request, slug, media_id):
    obj = _property(request, slug, "properties.update"); media = get_object_or_404(obj.media, pk=media_id)
    items = list(obj.media.order_by("sort_order", "pk")); index = items.index(media)
    target = index - 1 if request.POST.get("direction") == "up" else index + 1
    if 0 <= target < len(items):
        items[index], items[target] = items[target], items[index]
        for position, item in enumerate(items): item.sort_order = position
        PropertyMedia.objects.bulk_update(items, ("sort_order",))
    return redirect(f"/properties/{obj.slug}/?tab=media")


def media_download(request, media_id):
    media = get_object_or_404(PropertyMedia.objects.select_related("property"), pk=media_id)
    public = media.is_public and media.property.is_published and media.property.archived_at is None
    if not public and (not request.user.is_authenticated or not user_has_capability(request.user, "properties.view", media.property)): raise Http404
    return FileResponse(media.file.open("rb"), as_attachment=media.kind == PropertyMedia.Kind.DOCUMENT, filename=media.file.name.rsplit("/", 1)[-1])


@login_required
@require_POST
def media_delete(request, slug, media_id):
    obj = _property(request, slug, "properties.update"); media = get_object_or_404(obj.media, pk=media_id)
    storage, name = media.file.storage, media.file.name; media.delete(); transaction.on_commit(lambda: storage.delete(name))
    messages.success(request, _("Media removed.")); return redirect(f"/properties/{obj.slug}/?tab=media")


def _dataset(dataset):
    if dataset not in DATASETS: raise Http404
    return DATASETS[dataset]


def _transfer_allowed(user, definition, action):
    capability = f"{definition['permission']}.{action}"
    if user_has_capability(user, capability): return True
    if definition["permission"] in {"units", "unit-rates"} or action == "export":
        return properties_for_user(user, capability).exists()
    return False


@login_required
def transfer_center(request):
    if not any(_transfer_allowed(request.user, item, "import") or _transfer_allowed(request.user, item, "export") for item in DATASETS.values()): raise PermissionDenied
    return render(request, "properties/transfer.html", {"datasets": DATASETS})


@login_required
def transfer_template(request, dataset):
    definition = _dataset(dataset)
    if not _transfer_allowed(request.user, definition, "import"): raise PermissionDenied
    response = HttpResponse(template_csv(dataset), content_type="text/csv; charset=utf-8"); response["Content-Disposition"] = f'attachment; filename="{dataset}-template.csv"'; return response


@login_required
def transfer_export(request, dataset):
    definition = _dataset(dataset)
    if not _transfer_allowed(request.user, definition, "export"): raise PermissionDenied
    rows = export_rows(dataset, properties_for_user(request.user, f"{definition['permission']}.export"), sensitive=user_has_capability(request.user, "tenants.export_sensitive"))
    response = HttpResponse(csv_response_rows(dataset, rows), content_type="text/csv; charset=utf-8"); response["Content-Disposition"] = f'attachment; filename="{dataset}-export.csv"'; return response


@login_required
@require_POST
def transfer_preview(request, dataset):
    definition = _dataset(dataset)
    if not _transfer_allowed(request.user, definition, "import"): raise PermissionDenied
    upload = request.FILES.get("file")
    if not upload: messages.error(request, _("Choose a CSV file.")); return redirect("transfer_center")
    rows, errors = parse_csv(upload, dataset); prepared = []
    if not errors: prepared, errors = validate_rows(dataset, rows, request.user)
    token = secrets.token_urlsafe(18); request.session[f"csv_preview:{token}"] = {"dataset": dataset, "rows": rows}
    return render(request, "properties/transfer_preview.html", {"dataset": dataset, "rows": rows[:20], "row_count": len(rows), "valid_count": len(prepared), "errors": errors, "token": token})


@login_required
@require_POST
def transfer_commit(request, dataset):
    definition = _dataset(dataset)
    if not _transfer_allowed(request.user, definition, "import"): raise PermissionDenied
    preview = request.session.pop(f"csv_preview:{request.POST.get('token', '')}", None)
    if not preview or preview["dataset"] != dataset: messages.error(request, _("Import preview expired. Preview the CSV again.")); return redirect("transfer_center")
    prepared, errors = validate_rows(dataset, preview["rows"], request.user, persist=True)
    if errors: return render(request, "properties/transfer_preview.html", {"dataset": dataset, "rows": preview["rows"][:20], "row_count": len(preview["rows"]), "valid_count": len(prepared), "errors": errors, "token": ""})
    messages.success(request, _("Imported %(count)s %(dataset)s rows in one transaction.") % {"count": len(prepared), "dataset": dataset}); return redirect("transfer_center")
