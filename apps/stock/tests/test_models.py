"""Stock model invariants.

The status boundaries are the important part. `deriveStatus` in the
frontend's `lib/service-utils.ts` is three lines, and every one of them is an
inclusive comparison — a strict `<` anywhere here puts an article on the
wrong side of the low-stock alert.
"""

import pytest
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError

from apps.catalogue.tests.factories import ArticleFactory
from apps.stock.models import StockLevel, StockMovement
from apps.stock.tests.factories import StockLevelFactory, StockMovementFactory

pytestmark = pytest.mark.django_db


class TestStockLevelStatus:
    @pytest.mark.parametrize(
        ("quantity", "threshold", "expected"),
        [
            (0, 10, "OUT_OF_STOCK"),
            (0, 0, "OUT_OF_STOCK"),
            (1, 10, "LOW"),
            (9, 10, "LOW"),
            (10, 10, "LOW"),  # inclusive: quantity <= threshold
            (11, 10, "IN_STOCK"),
            (1, 0, "IN_STOCK"),  # no threshold set, any stock is fine
            (500, 10, "IN_STOCK"),
        ],
    )
    def test_boundaries_match_derive_status(self, site, quantity, threshold, expected):
        level = StockLevelFactory(quantity=quantity, reorder_threshold=threshold)
        assert level.status == expected


class TestStockLevel:
    def test_one_level_per_article_and_site(self, site):
        article = ArticleFactory()
        StockLevelFactory(article=article, site=site)
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                StockLevel.objects.create(article=article, site=site, quantity=5)

    def test_deleting_an_article_deletes_its_level(self, site):
        article = ArticleFactory()
        StockLevelFactory(article=article, site=site)
        article.delete()
        assert StockLevel.objects.count() == 0


class TestStockMovement:
    def test_an_article_with_movements_cannot_be_deleted(self, site, owner):
        movement = StockMovementFactory(user=owner)
        with pytest.raises(ProtectedError):
            movement.article.delete()

    def test_a_user_with_movements_cannot_be_deleted(self, site, owner):
        """Which is what makes sub-project 1's deactivate-never-delete policy
        load-bearing rather than decorative."""
        StockMovementFactory(user=owner)
        with pytest.raises(ProtectedError):
            owner.delete()

    def test_user_name_is_denormalised(self, site, owner):
        movement = StockMovementFactory(user=owner, user_name=owner.full_name)
        owner.full_name = "Nom Modifié"
        owner.save()
        movement.refresh_from_db()
        assert movement.user_name != "Nom Modifié"

    def test_default_ordering_is_newest_first(self, site, owner):
        first = StockMovementFactory(user=owner)
        second = StockMovementFactory(user=owner)
        assert list(StockMovement.objects.all()) == [second, first]
