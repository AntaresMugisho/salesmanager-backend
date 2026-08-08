"""The invariants that make three of the frontend's fallbacks unreachable here.

`features/reports/lib/*.ts` defends against a sold article missing from the
catalogue ("Sans catégorie"), a moved article missing from it ("Article
supprimé"), and a stock level whose article is gone. It has to: IndexedDB has
no foreign keys.

This backend does, so those branches are not implemented. These tests are what
make that a stated invariant rather than an assumption. If a migration ever
relaxes one of these foreign keys, one of these tests fails and points at the
builders that would then need a fallback.
"""

import pytest
from django.db.models import ProtectedError

from apps.catalogue.tests.factories import ArticleFactory, CategoryFactory
from apps.sales.tests.factories import SaleLineFactory
from apps.stock.tests.factories import StockMovementFactory

pytestmark = pytest.mark.django_db


class TestTheDatabaseRefusesTheDeletes:
    def test_a_sold_article_cannot_be_deleted(self):
        """Makes the profitability report's catalogue lookup total.

        `buildProfitabilityReport` falls back to "Sans catégorie" for a sold
        article missing from the catalogue. Here that state is unreachable.
        """
        sale_line = SaleLineFactory()

        with pytest.raises(ProtectedError):
            sale_line.article.delete()

    def test_a_moved_article_cannot_be_deleted(self):
        """Makes the stock journal's catalogue lookup total.

        `buildStockReport` falls back to "Article supprimé"; here the delete
        does not happen.
        """
        stock_movement = StockMovementFactory()

        with pytest.raises(ProtectedError):
            stock_movement.article.delete()

    def test_a_category_in_use_cannot_be_deleted(self):
        category = CategoryFactory()
        ArticleFactory(category=category)

        with pytest.raises(ProtectedError):
            category.delete()

    def test_an_article_with_no_history_can_still_be_deleted(self):
        """The invariants above are about *referenced* rows, not a ban.

        Without this, the three tests above would also pass if something
        blocked every delete for an unrelated reason.
        """
        orphan = ArticleFactory()

        orphan.delete()
