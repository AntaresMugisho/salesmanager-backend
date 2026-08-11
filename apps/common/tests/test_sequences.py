"""Document reference allocation.

The frontend counts rows to fake this and says so:

    Counting rows is adequate for a single-tab mock ONLY — the real backend
    owns numbering.

Allocation happens inside the caller's atomic block, which buys the property
asserted at the bottom of this file: a failed write rolls the counter back, so
a rejected document leaves no gap.
"""

import pytest
from django.db import transaction

from apps.common.models import DocumentSequence
from apps.common.sequences import next_reference, next_sku

pytestmark = pytest.mark.django_db


def allocate(prefix="TR", year=2026):
    with transaction.atomic():
        return next_reference(prefix, year)


def allocate_sku():
    with transaction.atomic():
        return next_sku()


class TestFormat:
    def test_the_first_reference_of_a_year_is_one(self):
        assert allocate() == "TR-2026-0001"

    def test_numbers_are_padded_to_four_digits(self):
        DocumentSequence.objects.create(prefix="TR", year=2026, last_number=41)
        assert allocate() == "TR-2026-0042"

    def test_padding_widens_past_four_digits(self):
        DocumentSequence.objects.create(prefix="TR", year=2026, last_number=9999)
        assert allocate() == "TR-2026-10000"


class TestSequencing:
    def test_consecutive_allocations_increment(self):
        assert [allocate() for _ in range(3)] == [
            "TR-2026-0001",
            "TR-2026-0002",
            "TR-2026-0003",
        ]

    def test_a_new_year_restarts_at_one(self):
        allocate(year=2026)
        allocate(year=2026)
        assert allocate(year=2027) == "TR-2027-0001"

    def test_a_new_year_leaves_the_old_counter_untouched(self):
        allocate(year=2026)
        allocate(year=2027)
        assert allocate(year=2026) == "TR-2026-0002"

    def test_prefixes_count_independently(self):
        """Sub-project 4 allocates FA- from this same table."""
        allocate(prefix="TR")
        allocate(prefix="TR")
        assert allocate(prefix="FA") == "FA-2026-0001"


class TestSku:
    """An article is not a document: its counter is not year-scoped."""

    def test_the_first_sku_is_one_padded_to_five_digits(self):
        assert allocate_sku() == "ART-00001"

    def test_consecutive_skus_increment(self):
        assert [allocate_sku() for _ in range(3)] == [
            "ART-00001",
            "ART-00002",
            "ART-00003",
        ]

    def test_padding_widens_past_five_digits(self):
        # update_or_create, not create: a later migration seeds this exact
        # row, and from then on `create` would violate
        # `one_sequence_per_prefix_and_year`. This form works either way.
        DocumentSequence.objects.update_or_create(
            prefix="ART", year=0, defaults={"last_number": 99999}
        )
        assert allocate_sku() == "ART-100000"

    def test_skus_do_not_share_a_counter_with_documents(self):
        """The decoy: if next_sku reused the TR/FA counter, or passed the
        current year, this would come back as ART-00003 or ART-2026-0001."""
        allocate(prefix="TR", year=2026)
        allocate(prefix="TR", year=2026)
        assert allocate_sku() == "ART-00001"

    def test_a_rolled_back_sku_leaves_no_gap(self):
        allocate_sku()

        with pytest.raises(RuntimeError):
            with transaction.atomic():
                next_sku()
                raise RuntimeError("something later in the write failed")

        assert allocate_sku() == "ART-00002"

    # `transaction=True` for the same reason as TestAtomicGuard below: the
    # ordinary django_db fixture already holds an atomic block open, so the
    # guard could never fire.
    @pytest.mark.django_db(transaction=True)
    def test_allocating_a_sku_outside_a_transaction_is_refused(self):
        with pytest.raises(RuntimeError, match="atomic"):
            next_sku()


class TestRollback:
    def test_a_rolled_back_allocation_leaves_no_gap(self):
        """The property that matters for sub-project 4, where the number is
        an invoice number rather than a delivery-note number."""
        allocate()

        with pytest.raises(RuntimeError):
            with transaction.atomic():
                next_reference("TR", 2026)
                raise RuntimeError("something later in the write failed")

        assert allocate() == "TR-2026-0002"


class TestAtomicGuard:
    # `transaction=True` is required, not decorative: the ordinary django_db
    # fixture wraps each test in its own atomic block, so `in_atomic_block` is
    # already True and the guard could never fire. This is the only way to
    # reach the state a bare production call would be in.
    @pytest.mark.django_db(transaction=True)
    def test_allocating_outside_a_transaction_is_refused(self):
        """Called bare, the read-modify-write would race silently instead of
        failing. Developer error, never user-facing — hence a plain
        RuntimeError and an English message."""
        with pytest.raises(RuntimeError, match="atomic"):
            next_reference("TR", 2026)


class TestModel:
    def test_one_counter_per_prefix_and_year(self):
        from django.db import IntegrityError

        DocumentSequence.objects.create(prefix="TR", year=2026)
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                DocumentSequence.objects.create(prefix="TR", year=2026)
