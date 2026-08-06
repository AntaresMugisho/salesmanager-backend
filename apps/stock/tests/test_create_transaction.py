"""Multi-line transaction creation.

Mirrors `createTransaction` in the frontend's services/stock.ts, with one
difference the spec calls out: numbering is real here.
"""

import pytest
from rest_framework.serializers import ValidationError

from apps.catalogue.tests.factories import ArticleFactory, SupplierFactory
from apps.common.models import DocumentSequence
from apps.stock.models import StockLevel, StockMovement, StockTransaction
from apps.stock.services import create_transaction
from apps.stock.tests.factories import StockLevelFactory

pytestmark = pytest.mark.django_db


def line(article, quantity, unit_cost=None):
    return {"article": article, "quantity": quantity, "unit_cost": unit_cost}


def build(site, user, lines, **kwargs):
    payload = {
        "type": "IN",
        "reason": "PURCHASE",
        "lines": lines,
        "user": user,
        "site": site,
    }
    payload.update(kwargs)
    return create_transaction(**payload)


class TestHeader:
    def test_the_reference_is_allocated(self, site, owner):
        header = build(site, owner, [line(ArticleFactory(), 5)])
        assert header.reference.startswith("TR-")
        assert header.reference.endswith("-0001")

    def test_consecutive_transactions_increment(self, site, owner):
        first = build(site, owner, [line(ArticleFactory(), 1)])
        second = build(site, owner, [line(ArticleFactory(), 1)])
        assert (
            int(second.reference.split("-")[-1])
            == int(first.reference.split("-")[-1]) + 1
        )

    def test_the_user_name_is_snapshotted(self, site, owner):
        header = build(site, owner, [line(ArticleFactory(), 1)])
        assert header.user_name == owner.full_name

    def test_the_supplier_name_is_snapshotted(self, site, owner):
        supplier = SupplierFactory(name="Brasimba")
        header = build(site, owner, [line(ArticleFactory(), 1)], supplier=supplier)
        assert header.supplier == supplier
        assert header.supplier_name == "Brasimba"

    def test_no_supplier_leaves_both_fields_null(self, site, owner):
        header = build(site, owner, [line(ArticleFactory(), 1)])
        assert header.supplier is None
        assert header.supplier_name is None

    def test_blank_strings_normalise_to_null(self, site, owner):
        header = build(
            site, owner, [line(ArticleFactory(), 1)], user_reference="  ", note=""
        )
        assert header.user_reference is None
        assert header.note is None


class TestCounts:
    def test_line_count_and_total_quantity(self, site, owner):
        header = build(
            site,
            owner,
            [line(ArticleFactory(), 4), line(ArticleFactory(), 6)],
        )
        assert header.line_count == 2
        assert header.total_quantity == 10
        assert header.lines.count() == 2

    def test_total_quantity_sums_derived_deltas_for_an_adjustment(self, site, owner):
        """An ADJUSTMENT line carries a counted *target*; the movement records
        the delta. The total must sum the deltas, not the targets."""
        first, second = ArticleFactory(), ArticleFactory()
        StockLevelFactory(article=first, site=site, quantity=20)
        StockLevelFactory(article=second, site=site, quantity=5)

        header = build(
            site,
            owner,
            [line(first, 14), line(second, 9)],
            type="ADJUSTMENT",
            reason="COUNT_CORRECTION",
        )

        # |14 - 20| = 6, |9 - 5| = 4
        assert header.total_quantity == 10


class TestReferenceSplit:
    def test_a_blank_user_reference_puts_the_tr_number_on_every_movement(
        self, site, owner
    ):
        header = build(site, owner, [line(ArticleFactory(), 1)])
        assert header.user_reference is None
        assert header.lines.get().reference == header.reference

    def test_a_supplied_user_reference_goes_to_the_movements(self, site, owner):
        header = build(site, owner, [line(ArticleFactory(), 1)], user_reference="BL-42")
        assert header.reference.startswith("TR-")
        assert header.user_reference == "BL-42"
        assert header.lines.get().reference == "BL-42"


class TestLines:
    def test_every_line_becomes_a_movement_carrying_the_header(self, site, owner):
        header = build(
            site, owner, [line(ArticleFactory(), 3), line(ArticleFactory(), 7)]
        )
        assert {m.quantity for m in header.lines.all()} == {3, 7}
        assert all(m.transaction == header for m in header.lines.all())

    def test_stock_levels_move(self, site, owner):
        article = ArticleFactory()
        StockLevelFactory(article=article, site=site, quantity=10)

        build(site, owner, [line(article, 5)])

        assert StockLevel.objects.get(article=article).quantity == 15

    def test_the_unit_cost_reaches_the_movement(self, site, owner):
        article = ArticleFactory()
        header = build(site, owner, [line(article, 5, unit_cost=800)])
        assert header.lines.get().unit_cost == 800


class TestAllOrNothing:
    def test_an_insufficient_line_writes_nothing(self, site, owner):
        good, bad = ArticleFactory(), ArticleFactory()
        StockLevelFactory(article=good, site=site, quantity=50)
        StockLevelFactory(article=bad, site=site, quantity=2)

        with pytest.raises(ValidationError) as exc:
            build(
                site,
                owner,
                [line(good, 10), line(bad, 99)],
                type="OUT",
                reason="SALE",
            )

        assert "lines.1.quantity" in exc.value.detail
        assert StockTransaction.objects.count() == 0
        assert StockMovement.objects.count() == 0
        assert StockLevel.objects.get(article=good).quantity == 50
        assert StockLevel.objects.get(article=bad).quantity == 2

    def test_a_failed_create_leaves_no_gap_in_the_sequence(self, site, owner):
        good = ArticleFactory()
        StockLevelFactory(article=good, site=site, quantity=1)
        build(site, owner, [line(ArticleFactory(), 1)])  # TR-....-0001

        with pytest.raises(ValidationError):
            build(site, owner, [line(good, 99)], type="OUT", reason="SALE")

        header = build(site, owner, [line(ArticleFactory(), 1)])
        assert header.reference.endswith("-0002")

    def test_an_unchanged_adjustment_line_aborts_the_whole_transaction(
        self, site, owner
    ):
        article = ArticleFactory()
        StockLevelFactory(article=article, site=site, quantity=9)

        with pytest.raises(ValidationError) as exc:
            build(
                site,
                owner,
                [line(article, 9)],
                type="ADJUSTMENT",
                reason="COUNT_CORRECTION",
            )

        assert "lines.0.quantity" in exc.value.detail
        assert StockTransaction.objects.count() == 0


class TestSequenceState:
    def test_the_counter_row_tracks_the_allocations(self, site, owner):
        build(site, owner, [line(ArticleFactory(), 1)])
        build(site, owner, [line(ArticleFactory(), 1)])

        sequence = DocumentSequence.objects.get(prefix="TR")
        assert sequence.last_number == 2
