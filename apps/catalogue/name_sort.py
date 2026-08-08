"""Backfill for the `name_sort` column.

A module rather than migration-only code so it can be unit-tested against the
real models: the migration passes its historical models to the same function.

Historical models carry no `save()` override, which is why this sets the field
explicitly and uses `bulk_update`.
"""

from apps.common.collation import collation_key


def rebuild_name_sort(*models) -> None:
    """Recompute `name_sort` for every row of each model given."""
    for model in models:
        rows = list(model.objects.all().only("id", "name", "name_sort"))
        for row in rows:
            row.name_sort = collation_key(row.name)
        model.objects.bulk_update(rows, ["name_sort"], batch_size=500)
