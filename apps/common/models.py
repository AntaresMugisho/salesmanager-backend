from uuid import uuid4

from django.db import models

from apps.common.collation import collation_key


class NameSortedModel(models.Model):
    """Keeps a `name_sort` column in step with `name`.

    The concrete model declares the field, because `max_length` differs per
    model and must be twice the source `name`'s length — ligature expansion
    makes the key longer than its input.

    Sorting has to stay in SQL: a Python `sorted()` would order the current
    page rather than the table, which is silently wrong under pagination.
    """

    class Meta:
        abstract = True

    def save(self, **kwargs):
        self.name_sort = collation_key(self.name)
        # A caller that saves only `name` would otherwise leave a stale key on
        # the row while the in-memory instance looked correct.
        update_fields = kwargs.get("update_fields")
        if update_fields is not None and "name" in update_fields:
            kwargs["update_fields"] = {*update_fields, "name_sort"}
        super().save(**kwargs)


class UUIDModel(models.Model):
    """Base for every domain model in every sub-project.

    UUID primary keys because the frontend's `UUID` type says so, and because
    they let the frontend mint optimistic ids if it ever needs to.
    """

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class DocumentSequence(models.Model):
    """One counter row per document prefix and year.

    Deliberately *not* a UUIDModel. This is infrastructure, not a domain
    object: nothing links to it, nothing serialises it, and no API exposes
    it. A plain auto pk is the honest shape.

    Sub-project 3 allocates `TR-`; sub-project 4 allocates `FA-` from this
    same table with no change.
    """

    prefix = models.CharField(max_length=8)
    year = models.PositiveIntegerField()
    last_number = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "séquence de document"
        verbose_name_plural = "séquences de document"
        constraints = [
            models.UniqueConstraint(
                fields=["prefix", "year"],
                name="one_sequence_per_prefix_and_year",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.prefix}-{self.year}: {self.last_number}"
