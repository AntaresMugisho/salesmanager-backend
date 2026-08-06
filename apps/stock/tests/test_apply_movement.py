"""The single writer of a stock quantity.

Mirrors `applyMovementLine` in the frontend's services/stock.ts, including
the ADJUSTMENT semantics: `quantity` is the counted *target*, and the
movement records the delta that was applied.
"""

import pytest
from rest_framework.serializers import ValidationError

from apps.catalogue.tests.factories import ArticleFactory
from apps.stock.models import StockLevel, StockMovement
from apps.stock.services import apply_movement
from apps.stock.tests.factories import StockLevelFactory

pytestmark = pytest.mark.django_db


def post(article, site, user, **kwargs):
    defaults = {
        "article": article,
        "site": site,
        "type": "IN",
        "reason": "PURCHASE",
        "quantity": 10,
        "user": user,
    }
    defaults.update(kwargs)
    return apply_movement(**defaults)


class TestIn:
    def test_adds_to_the_level(self, site, owner):
        article = ArticleFactory()
        StockLevelFactory(article=article, site=site, quantity=5)

        movement = post(article, site, owner, type="IN", quantity=10)

        assert movement.quantity_before == 5
        assert movement.quantity_after == 15
        assert movement.quantity == 10
        assert StockLevel.objects.get().quantity == 15

    def test_creates_the_level_when_absent(self, site, owner):
        article = ArticleFactory()
        movement = post(article, site, owner, type="IN", quantity=7)

        assert movement.quantity_before == 0
        assert movement.quantity_after == 7
        assert StockLevel.objects.get(article=article).quantity == 7


class TestOut:
    def test_subtracts_from_the_level(self, site, owner):
        article = ArticleFactory()
        StockLevelFactory(article=article, site=site, quantity=20)

        movement = post(article, site, owner, type="OUT", reason="SALE", quantity=8)

        assert movement.quantity_before == 20
        assert movement.quantity_after == 12
        assert movement.quantity == 8
        assert StockLevel.objects.get().quantity == 12

    def test_may_empty_the_level_exactly(self, site, owner):
        article = ArticleFactory()
        StockLevelFactory(article=article, site=site, quantity=8)
        movement = post(article, site, owner, type="OUT", reason="SALE", quantity=8)
        assert movement.quantity_after == 0

    def test_refuses_to_go_negative(self, site, owner):
        article = ArticleFactory()
        StockLevelFactory(article=article, site=site, quantity=3)

        with pytest.raises(ValidationError) as exc:
            post(article, site, owner, type="OUT", reason="SALE", quantity=4)

        assert exc.value.detail["quantity"][0] == (
            "Stock insuffisant : 3 unité(s) disponible(s) actuellement."
        )

    def test_a_refused_movement_writes_nothing(self, site, owner):
        article = ArticleFactory()
        StockLevelFactory(article=article, site=site, quantity=3)

        with pytest.raises(ValidationError):
            post(article, site, owner, type="OUT", reason="SALE", quantity=4)

        assert StockMovement.objects.count() == 0
        assert StockLevel.objects.get().quantity == 3


class TestAdjustment:
    def test_quantity_is_the_counted_target_not_a_delta(self, site, owner):
        article = ArticleFactory()
        StockLevelFactory(article=article, site=site, quantity=20)

        movement = post(
            article,
            site,
            owner,
            type="ADJUSTMENT",
            reason="COUNT_CORRECTION",
            quantity=14,
        )

        assert movement.quantity_before == 20
        assert movement.quantity_after == 14
        assert movement.quantity == 6  # the delta that was applied
        assert StockLevel.objects.get().quantity == 14

    def test_adjusting_upward(self, site, owner):
        article = ArticleFactory()
        StockLevelFactory(article=article, site=site, quantity=5)

        movement = post(
            article,
            site,
            owner,
            type="ADJUSTMENT",
            reason="COUNT_CORRECTION",
            quantity=12,
        )

        assert movement.quantity_after == 12
        assert movement.quantity == 7

    def test_adjusting_to_zero_is_allowed(self, site, owner):
        article = ArticleFactory()
        StockLevelFactory(article=article, site=site, quantity=5)
        movement = post(
            article,
            site,
            owner,
            type="ADJUSTMENT",
            reason="COUNT_CORRECTION",
            quantity=0,
        )
        assert movement.quantity_after == 0
        assert movement.quantity == 5

    def test_an_unchanged_count_is_rejected(self, site, owner):
        article = ArticleFactory()
        StockLevelFactory(article=article, site=site, quantity=9)

        with pytest.raises(ValidationError) as exc:
            post(
                article,
                site,
                owner,
                type="ADJUSTMENT",
                reason="COUNT_CORRECTION",
                quantity=9,
            )

        assert exc.value.detail["quantity"][0] == (
            "La quantité comptée est identique au stock actuel."
        )


class TestFieldPrefix:
    def test_routes_the_error_to_a_line(self, site, owner):
        """Sub-project 3 posts several lines at once and needs the error to
        land on the right form row."""
        article = ArticleFactory()
        StockLevelFactory(article=article, site=site, quantity=1)

        with pytest.raises(ValidationError) as exc:
            post(
                article,
                site,
                owner,
                type="OUT",
                reason="SALE",
                quantity=5,
                field_prefix="lines.2.",
            )

        assert "lines.2.quantity" in exc.value.detail


class TestRecordedFields:
    def test_the_user_name_is_denormalised(self, site, owner):
        article = ArticleFactory()
        movement = post(article, site, owner)
        assert movement.user_name == owner.full_name

    def test_blank_reference_and_note_become_null(self, site, owner):
        article = ArticleFactory()
        movement = post(article, site, owner, reference="  ", note="")
        assert movement.reference is None
        assert movement.note is None

    def test_the_reference_and_note_are_trimmed(self, site, owner):
        article = ArticleFactory()
        movement = post(article, site, owner, reference="  BL-42 ", note=" Reçu ")
        assert movement.reference == "BL-42"
        assert movement.note == "Reçu"


class TestTransactionLink:
    def test_a_movement_defaults_to_no_transaction(self, site, owner):
        article = ArticleFactory()
        assert post(article, site, owner).transaction is None

    def test_a_movement_can_be_linked_to_a_header(self, site, owner):
        from apps.stock.tests.factories import StockTransactionFactory

        article = ArticleFactory()
        header = StockTransactionFactory(user=owner)

        movement = post(article, site, owner, stock_transaction=header)

        assert movement.transaction == header
        assert list(header.lines.all()) == [movement]
