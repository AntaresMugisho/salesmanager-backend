"""Document reference and article SKU allocation.

`TR-YYYY-NNNN` for stock transactions, `FA-YYYY-NNNN` for sales invoices,
`ART-NNNNN` for article SKUs. One locking implementation, three formats.
"""

from django.db import connection

from apps.common.models import DocumentSequence

#: Article SKUs share the counter table but not its year-scoping: an article
#: does not belong to a financial year. Not NULL — Postgres treats NULLs as
#: distinct in a unique constraint, so a nullable year would permit two `ART`
#: rows and silently hand out duplicate numbers. 0 keeps
#: `one_sequence_per_prefix_and_year` doing its job, with no schema change.
SKU_PREFIX = "ART"
SKU_YEAR = 0


def _next_number(prefix: str, year: int) -> int:
    """Allocate and return the next raw counter value for `prefix`/`year`.

    MUST be called inside an open `transaction.atomic()` block. Two
    consequences follow from that, and both are wanted:

    - The `select_for_update` below only serialises concurrent allocations if
      a transaction is already open. Called bare it would race silently.
    - The increment is rolled back with the caller's write, so a document that
      fails validation leaves no gap in the sequence.

    Note that `select_for_update` is a silent no-op on SQLite — verified,
    `connection.features.has_select_for_update` is False and the call neither
    locks nor raises. The serialisation is real only on PostgreSQL.
    """
    if not connection.in_atomic_block:
        raise RuntimeError(
            "Sequence allocation must happen inside transaction.atomic()."
        )

    # get_or_create's documented IntegrityError-and-re-get path handles two
    # requests racing to create the first row of a year.
    sequence, _ = DocumentSequence.objects.get_or_create(prefix=prefix, year=year)

    locked = DocumentSequence.objects.select_for_update().get(pk=sequence.pk)
    locked.last_number += 1
    locked.save(update_fields=["last_number"])

    return locked.last_number


def next_reference(prefix: str, year: int) -> str:
    """Allocate the next `PREFIX-YYYY-NNNN`."""
    return f"{prefix}-{year}-{_next_number(prefix, year):04d}"


def next_sku() -> str:
    """Allocate the next `ART-NNNNN`."""
    return f"{SKU_PREFIX}-{_next_number(SKU_PREFIX, SKU_YEAR):05d}"
