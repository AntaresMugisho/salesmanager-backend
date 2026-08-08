"""The reports' ORM seam, and the three fields the finance seam gains.

Not range-filtered, deliberately — inventory is as-of-now and the
period-scoped folds filter in Python through `in_range`, so the
inclusive-bounds rule lives in exactly one tested place.
"""

from datetime import date
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from apps.accounts.models import Site
from apps.catalogue.tests.factories import (
    ArticleFactory,
    CategoryFactory,
    SupplierFactory,
)
from apps.finance.aggregate import summarise
from apps.finance.facts import load_facts
from apps.reports.facts import load_report_facts
from apps.sales.tests.factories import CustomerFactory, SaleFactory, SaleLineFactory
from apps.stock.tests.factories import (
    StockLevelFactory,
    StockMovementFactory,
    StockTransactionFactory,
)

pytestmark = pytest.mark.django_db

KINSHASA = ZoneInfo("Africa/Kinshasa")


class TestTheFinanceSeamIsWidened:
    def test_a_sale_carries_its_customer_and_discount(self, site):
        customer = CustomerFactory(name="Alice Byamungu")
        SaleFactory(customer=customer, customer_name=customer.name, discount=1_500)

        row = load_facts(site)["sales"][0]

        assert row["customer_id"] == customer.id
        assert row["discount"] == 1_500

    def test_a_walk_in_sale_carries_a_null_customer(self, site):
        SaleFactory(customer=None, customer_name=None)

        row = load_facts(site)["sales"][0]

        assert row["customer_id"] is None

    def test_a_line_carries_its_vat_rate(self, site):
        SaleLineFactory(vat_rate=Decimal("16.00"))

        row = load_facts(site)["lines"][0]

        assert row["vat_rate"] == Decimal("16.00")

    def test_the_finance_folds_still_work_on_the_widened_facts(self, site):
        # Adding keys cannot affect folds that name the fields they read, but
        # this is the assertion that says so rather than assuming it.
        SaleLineFactory()

        result = summarise(
            load_facts(site),
            KINSHASA,
            date(2026, 1, 1),
            date(2026, 12, 31),
        )

        assert "revenue" in result


class TestTheCatalogueIndex:
    def test_it_is_keyed_by_article_id_and_resolves_the_category(self, site):
        category = CategoryFactory(name="Épicerie")
        article = ArticleFactory(
            name="Riz", sku="ART-9001", category=category, purchase_price=800
        )

        catalogue = load_report_facts(site)["catalogue"]

        assert catalogue[article.id] == {
            "article_id": article.id,
            "sku": "ART-9001",
            "name": "Riz",
            "unit": article.unit,
            "purchase_price": 800,
            "category_id": category.id,
            "category_name": "Épicerie",
        }

    def test_it_is_not_site_scoped(self, site):
        # Articles and categories carry no site of their own, so every article
        # is present whichever site is asked for.
        article = ArticleFactory()

        catalogue = load_report_facts(site)["catalogue"]

        assert article.id in catalogue


class TestSiteScoping:
    """Levels and movements *are* site-scoped; the catalogue is not.

    `Site.save()` refuses a second row today, so the second site here is
    inserted through `bulk_create`, which does not call `save()`. The bypass is
    deliberate: the `filter(site=...)` in the seam is real code that nothing
    else would catch the removal of, and `SiteManager.current` documents
    multi-site as a future migration rather than a rewrite. These two tests are
    what make that migration safe.
    """

    @pytest.fixture
    def other_site(self, site):
        rows = Site.objects.bulk_create(
            [
                Site(
                    name="Dépôt Katindo",
                    address="4 avenue du Lac, Goma",
                    is_default=False,
                )
            ]
        )
        return rows[0]

    def test_levels_from_another_site_are_absent(self, site, other_site):
        article = ArticleFactory()
        StockLevelFactory(article=article, site=other_site, quantity=7)

        levels = load_report_facts(site)["levels"]

        assert levels == []

    def test_movements_from_another_site_are_absent(self, site, other_site):
        StockMovementFactory(site=other_site)

        movements = load_report_facts(site)["movements"]

        assert movements == []

    def test_this_sites_level_is_present(self, site):
        article = ArticleFactory()
        StockLevelFactory(article=article, site=site, quantity=7, reorder_threshold=3)

        levels = load_report_facts(site)["levels"]

        assert levels == [
            {"article_id": article.id, "quantity": 7, "reorder_threshold": 3}
        ]


class TestSuppliers:
    def test_a_transaction_maps_to_its_supplier(self, site):
        supplier = SupplierFactory(name="Grossiste Kivu")
        transaction = StockTransactionFactory(
            site=site, supplier=supplier, supplier_name=supplier.name
        )

        rows = load_report_facts(site)

        assert rows["supplier_by_transaction"][transaction.id] == supplier.id
        assert rows["supplier_names"][supplier.id] == "Grossiste Kivu"

    def test_supplier_names_are_current_not_snapshotted(self, site):
        # Matches the frontend, which resolves names from the suppliers table
        # rather than the transaction's supplier_name snapshot.
        supplier = SupplierFactory(name="Ancien nom")
        StockTransactionFactory(site=site, supplier=supplier, supplier_name="Ancien nom")
        supplier.name = "Nouveau nom"
        supplier.save()

        rows = load_report_facts(site)

        assert rows["supplier_names"][supplier.id] == "Nouveau nom"

    def test_a_transaction_without_a_supplier_maps_to_none(self, site):
        transaction = StockTransactionFactory(site=site, supplier=None)

        rows = load_report_facts(site)

        assert rows["supplier_by_transaction"][transaction.id] is None

    def test_a_movement_outside_any_transaction_has_no_transaction_id(self, site):
        StockMovementFactory(site=site, transaction=None)

        movements = load_report_facts(site)["movements"]

        assert movements[0]["transaction_id"] is None


class TestQueryCount:
    """Flat regardless of volume: the seam reads a fixed set of querysets."""

    QUERIES = 5

    def build(self, site, count):
        category = CategoryFactory()
        for index in range(count):
            article = ArticleFactory(category=category)
            StockLevelFactory(article=article, site=site, quantity=index + 1)
            StockMovementFactory(article=article, site=site)

    def test_one_article(self, site, django_assert_num_queries):
        self.build(site, 1)
        with django_assert_num_queries(self.QUERIES):
            load_report_facts(site)

    def test_five_articles_cost_the_same(self, site, django_assert_num_queries):
        self.build(site, 5)
        with django_assert_num_queries(self.QUERIES):
            load_report_facts(site)
