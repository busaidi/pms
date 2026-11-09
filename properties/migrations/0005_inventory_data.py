from django.db import migrations
from django.utils.text import slugify


def forwards(apps, schema_editor):
    PropertyType = apps.get_model("properties", "PropertyType")
    Property = apps.get_model("properties", "Property")
    Unit = apps.get_model("properties", "Unit")
    UnitType = apps.get_model("properties", "UnitType")
    Region = apps.get_model("properties", "Region")
    City = apps.get_model("properties", "City")

    used_types = set()
    for item in PropertyType.objects.order_by("pk"):
        base = slugify(item.name) or "property-type"
        value, number = base, 2
        while value in used_types:
            value, number = f"{base}-{number}", number + 1
        item.slug = value; item.save(update_fields=("slug",)); used_types.add(value)

    region_cache = {}
    for item in Property.objects.order_by("pk"):
        changes = []
        if item.rental_mode == "whole":
            item.rental_mode = "whole_property"; changes.append("rental_mode")
        if item.is_public:
            item.is_published = True; item.public_slug = item.slug; changes += ["is_published", "public_slug"]
        region_name = item.region or "Muscat"
        region = region_cache.get(region_name)
        if not region:
            region, _ = Region.objects.get_or_create(country_code="OM", name=region_name); region_cache[region_name] = region
        city, _ = City.objects.get_or_create(region=region, name=item.city or "Muscat")
        item.region_ref_id = region.pk; item.city_ref_id = city.pk; changes += ["region_ref", "city_ref"]
        item.save(update_fields=changes)

    for prop in Property.objects.all():
        used = set()
        for unit in Unit.objects.filter(property=prop).order_by("pk"):
            base = slugify(unit.name) or "unit"; value, number = base, 2
            while value in used:
                value, number = f"{base}-{number}", number + 1
            unit.slug = value; unit.furnishing = "furnished" if unit.is_furnished else "unfurnished"
            unit.save(update_fields=("slug", "furnishing")); used.add(value)
        used = set()
        for item in UnitType.objects.filter(property=prop).order_by("pk"):
            base = slugify(item.name) or "unit-type"; value, number = base, 2
            while value in used:
                value, number = f"{base}-{number}", number + 1
            item.public_slug = value; item.save(update_fields=("public_slug",)); used.add(value)


class Migration(migrations.Migration):
    dependencies = [("properties", "0004_alter_property_created_at_alter_property_updated_at_and_more")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
