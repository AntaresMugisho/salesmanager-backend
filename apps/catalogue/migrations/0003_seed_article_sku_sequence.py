"""Seed the ART counter past any hand-typed `ART-<n>` SKU.

Legacy SKUs are kept as they are, so the generator must start above the
highest number already in use or its first allocation could collide with one.
"""

import re

from django.db import migrations

LEGACY_ART_SKU = re.compile(r"^ART-(\d+)$", re.IGNORECASE)


def seed_counter(apps, schema_editor):
    Article = apps.get_model("catalogue", "Article")
    DocumentSequence = apps.get_model("common", "DocumentSequence")

    highest = 0
    for sku in Article.objects.values_list("sku", flat=True):
        match = LEGACY_ART_SKU.match(sku or "")
        if match:
            highest = max(highest, int(match.group(1)))

    # get_or_create, not update_or_create: re-running must never wind an
    # existing counter backwards.
    DocumentSequence.objects.get_or_create(
        prefix="ART", year=0, defaults={"last_number": highest}
    )


def drop_counter(apps, schema_editor):
    DocumentSequence = apps.get_model("common", "DocumentSequence")
    DocumentSequence.objects.filter(prefix="ART", year=0).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("catalogue", "0002_add_name_sort"),
        ("common", "0001_initial"),
    ]

    operations = [migrations.RunPython(seed_counter, drop_counter)]
