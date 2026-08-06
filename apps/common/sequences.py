"""Document reference allocation.

`TR-YYYY-NNNN` for stock transactions, `FA-YYYY-NNNN` for sales invoices in
sub-project 4. One implementation, two prefixes.
"""

from django.db import connection

from apps.common.models import DocumentSequence


def next_reference(prefix: str, year: int) -> str:
    """Allocate the next `PREFIX-YYYY-NNNN`.

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
        raise RuntimeError("next_reference must be called inside transaction.atomic().")

    # get_or_create's documented IntegrityError-and-re-get path handles two
    # requests racing to create the first row of a year.
    sequence, _ = DocumentSequence.objects.get_or_create(prefix=prefix, year=year)

    locked = DocumentSequence.objects.select_for_update().get(pk=sequence.pk)
    locked.last_number += 1
    locked.save(update_fields=["last_number"])

    return f"{prefix}-{year}-{locked.last_number:04d}"
