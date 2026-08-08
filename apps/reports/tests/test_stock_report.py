"""Stock et mouvements.

Two halves that do not share a date. The inventory tests assert that the range
is ignored; the movement tests assert that it is not. Getting either backwards
produces a document that looks plausible and is wrong.
"""

from datetime import date

import pytest

from apps.catalogue.tests.factories import ArticleFactory, CategoryFactory
from apps.reports.stock import NO_SUPPLIER_LABEL, build_stock_report
from apps.reports.tests.support import GENERATED_AT, JULY, KINSHASA, PARAMS, at
from apps.stock.tests.factories import StockLevelFactory, StockMovementFactory

URL = "/api/reports/stock/"

#: The endpoint's query count, measured. The point of the two tests that use it
#: is that they agree with each other, not the particular value.
FLAT_QUERY_COUNT = 7


def article(article_id, name, category_id, category_name, sku="ART-1", price=1_000):
    return {
        "article_id": article_id,
        "sku": sku,
        "name": name,
        "unit": "PIECE",
        "purchase_price": price,
        "category_id": category_id,
        "category_name": category_name,
    }


def level(article_id, quantity=10, reorder_threshold=0):
    return {
        "article_id": article_id,
        "quantity": quantity,
        "reorder_threshold": reorder_threshold,
    }


def movement(
    id="m1",
    day=15,
    month=7,
    article_id="a1",
    type="IN",
    reason="PURCHASE",
    quantity=10,
    unit_cost=800,
    transaction_id=None,
    reference=None,
):
    return {
        "id": id,
        "created_at": at(day, month=month),
        "article_id": article_id,
        "type": type,
        "reason": reason,
        "quantity": quantity,
        "quantity_before": 0,
        "quantity_after": quantity,
        "unit_cost": unit_cost,
        "reference": reference,
        "transaction_id": transaction_id,
        "user_name": "Utilisateur 1",
    }


def rows(catalogue=None, levels=None, movements=None, suppliers=None, by_tx=None):
    return {
        "catalogue": catalogue or {"a1": article("a1", "Riz", "c1", "Épicerie")},
        "levels": levels or [],
        "movements": movements or [],
        "supplier_by_transaction": by_tx or {},
        "supplier_names": suppliers or {},
    }


def build(**kw):
    return build_stock_report(rows(**kw), KINSHASA, *JULY, GENERATED_AT)


class TestInventory:
    def test_value_is_quantity_times_the_current_purchase_price(self):
        result = build(
            catalogue={"a1": article("a1", "Riz", "c1", "Épicerie", price=800)},
            levels=[level("a1", quantity=5)],
        )
        assert result["categories"][0]["articles"][0]["value"] == 4_000

    def test_a_groups_value_is_the_sum_of_its_articles(self):
        result = build(
            catalogue={
                "a1": article("a1", "Riz", "c1", "Épicerie", price=800),
                "a2": article("a2", "Sel", "c1", "Épicerie", price=200),
            },
            levels=[level("a1", quantity=5), level("a2", quantity=10)],
        )
        assert result["categories"][0]["value"] == 4_000 + 2_000

    def test_the_totals_count_articles_not_categories(self):
        result = build(
            catalogue={
                "a1": article("a1", "Riz", "c1", "Épicerie"),
                "a2": article("a2", "Jus", "c2", "Boissons"),
            },
            levels=[level("a1"), level("a2")],
        )
        assert len(result["categories"]) == 2
        assert result["stock_totals"]["article_count"] == 2

    def test_inventory_ignores_the_range_entirely(self):
        """The half of the document that is as-of-now.

        Asked for a range in 1999, the inventory still reports today's stock.
        This is the rule most likely to be "fixed" into a bug later.
        """
        result = build_stock_report(
            rows(levels=[level("a1", quantity=5)]),
            KINSHASA,
            date(1999, 1, 1),
            date(1999, 12, 31),
            GENERATED_AT,
        )
        assert result["stock_totals"]["article_count"] == 1
        assert result["categories"][0]["articles"][0]["quantity"] == 5

    @pytest.mark.parametrize(
        "quantity,threshold,expected",
        [
            (0, 5, "OUT_OF_STOCK"),
            (5, 5, "LOW"),
            (6, 5, "IN_STOCK"),
        ],
    )
    def test_status_follows_the_canonical_rule(self, quantity, threshold, expected):
        result = build(
            levels=[level("a1", quantity=quantity, reorder_threshold=threshold)]
        )
        assert result["categories"][0]["articles"][0]["status"] == expected


class TestFrenchOrdering:
    def test_categories_sort_by_the_collation_key(self):
        # Byte order would put Épicerie last, after Zeste.
        result = build(
            catalogue={
                "a1": article("a1", "Riz", "c1", "Épicerie"),
                "a2": article("a2", "Jus", "c2", "Zeste"),
                "a3": article("a3", "Sel", "c3", "Fruits"),
            },
            levels=[level("a1"), level("a2"), level("a3")],
        )
        names = [group["category_name"] for group in result["categories"]]
        assert names == ["Épicerie", "Fruits", "Zeste"]

    def test_articles_within_a_group_sort_by_the_collation_key(self):
        # Œufs must fall between Fruits and Oignons, not after Zeste.
        result = build(
            catalogue={
                "a1": article("a1", "Oignons", "c1", "Épicerie"),
                "a2": article("a2", "Œufs", "c1", "Épicerie"),
                "a3": article("a3", "Fruits", "c1", "Épicerie"),
            },
            levels=[level("a1"), level("a2"), level("a3")],
        )
        names = [row["name"] for row in result["categories"][0]["articles"]]
        assert names == ["Fruits", "Œufs", "Oignons"]

    def test_a_collation_tie_is_broken_deterministically(self):
        result = build(
            catalogue={
                "b": article("b", "Café", "c1", "Épicerie"),
                "a": article("a", "Cafe", "c1", "Épicerie"),
            },
            levels=[level("a"), level("b")],
        )
        ids = [row["article_id"] for row in result["categories"][0]["articles"]]
        assert ids == ["a", "b"]


class TestMovementSummary:
    def test_it_folds_by_type_and_reason(self):
        result = build(
            movements=[movement(id="m1", quantity=10), movement(id="m2", quantity=4)]
        )
        assert result["movement_summary"] == [
            {"type": "IN", "reason": "PURCHASE", "movement_count": 2, "quantity": 14}
        ]

    def test_it_uses_the_fixed_order_not_alphabetical(self):
        result = build(
            movements=[
                movement(id="m1", type="ADJUSTMENT", reason="COUNT_CORRECTION"),
                movement(id="m2", type="OUT", reason="SALE"),
                movement(id="m3", type="IN", reason="PURCHASE"),
            ]
        )
        assert [row["type"] for row in result["movement_summary"]] == [
            "IN",
            "OUT",
            "ADJUSTMENT",
        ]

    def test_reasons_within_a_type_use_the_fixed_order(self):
        result = build(
            movements=[
                movement(id="m1", type="OUT", reason="LOSS"),
                movement(id="m2", type="OUT", reason="SALE"),
                movement(id="m3", type="OUT", reason="DAMAGE"),
            ]
        )
        assert [row["reason"] for row in result["movement_summary"]] == [
            "SALE",
            "DAMAGE",
            "LOSS",
        ]

    def test_movements_outside_the_range_are_excluded(self):
        result = build(
            movements=[movement(id="m1", day=3, month=6), movement(id="m2", day=15)]
        )
        assert result["movement_summary"][0]["movement_count"] == 1


class TestSupplierPurchases:
    def test_only_purchases_count(self):
        result = build(
            movements=[
                movement(id="m1", type="IN", reason="PURCHASE"),
                movement(id="m2", type="OUT", reason="SALE"),
                movement(id="m3", type="IN", reason="RETURN"),
            ]
        )
        assert sum(row["movement_count"] for row in result["supplier_purchases"]) == 1

    def test_a_purchase_without_a_unit_cost_contributes_zero(self):
        """Never the article's current price.

        Valuing it at today's price would rewrite what the period actually
        cost; the count keeps the omission visible instead.
        """
        result = build(
            catalogue={"a1": article("a1", "Riz", "c1", "Épicerie", price=999)},
            movements=[movement(id="m1", quantity=10, unit_cost=None)],
        )
        row = result["supplier_purchases"][0]
        assert row["cost"] == 0
        assert row["without_cost_count"] == 1
        assert row["quantity"] == 10

    def test_a_purchase_with_no_transaction_folds_onto_the_unnamed_row(self):
        result = build(movements=[movement(id="m1", transaction_id=None)])
        row = result["supplier_purchases"][0]
        assert row["supplier_id"] is None
        assert row["supplier_name"] == NO_SUPPLIER_LABEL

    def test_a_transaction_naming_no_supplier_folds_onto_the_same_row(self):
        result = build(
            movements=[
                movement(id="m1", transaction_id="t1"),
                movement(id="m2", transaction_id=None),
            ],
            by_tx={"t1": None},
        )
        assert len(result["supplier_purchases"]) == 1
        assert result["supplier_purchases"][0]["movement_count"] == 2

    def test_a_named_supplier_uses_its_current_name(self):
        result = build(
            movements=[movement(id="m1", transaction_id="t1")],
            by_tx={"t1": "sup1"},
            suppliers={"sup1": "Grossiste Kivu"},
        )
        assert result["supplier_purchases"][0]["supplier_name"] == "Grossiste Kivu"

    def test_rows_are_largest_cost_first(self):
        result = build(
            movements=[
                movement(id="m1", transaction_id="t1", quantity=1, unit_cost=100),
                movement(id="m2", transaction_id="t2", quantity=10, unit_cost=100),
            ],
            by_tx={"t1": "sup1", "t2": "sup2"},
            suppliers={"sup1": "Petit", "sup2": "Grand"},
        )
        assert [row["supplier_name"] for row in result["supplier_purchases"]] == [
            "Grand",
            "Petit",
        ]


class TestJournal:
    def test_it_is_oldest_first(self):
        result = build(
            movements=[movement(id="late", day=20), movement(id="early", day=2)]
        )
        assert [row["id"] for row in result["journal"]] == ["early", "late"]

    def test_a_tie_is_broken_by_id(self):
        first = build(movements=[movement(id="b", day=9), movement(id="a", day=9)])
        second = build(movements=[movement(id="a", day=9), movement(id="b", day=9)])
        assert [row["id"] for row in first["journal"]] == ["a", "b"]
        assert [row["id"] for row in second["journal"]] == ["a", "b"]

    def test_it_names_the_article_from_the_catalogue(self):
        result = build(movements=[movement(id="m1", article_id="a1")])
        assert result["journal"][0]["article_name"] == "Riz"

    def test_movements_outside_the_range_are_excluded(self):
        result = build(movements=[movement(id="m1", day=3, month=6)])
        assert result["journal"] == []


@pytest.mark.django_db
class TestTheEndpoint:
    def test_a_cashier_is_refused(self, auth_client, cashier, site):
        assert auth_client(cashier).get(URL, PARAMS).status_code == 403

    def test_both_bounds_are_required(self, auth_client, manager, site):
        response = auth_client(manager).get(URL)
        assert response.status_code == 400
        assert set(response.json()["fieldErrors"]) == {"from", "to"}

    def test_an_empty_shop_is_zeroed_not_a_404(self, auth_client, manager, site):
        response = auth_client(manager).get(URL, PARAMS)
        assert response.status_code == 200
        body = response.json()
        assert body["categories"] == []
        assert body["stockTotals"] == {"articleCount": 0, "value": 0}
        assert body["journal"] == []

    def test_accented_categories_are_not_last(self, auth_client, manager, site):
        for name in ["Zeste", "Épicerie"]:
            category = CategoryFactory(name=name)
            stocked = ArticleFactory(category=category)
            StockLevelFactory(article=stocked, site=site, quantity=3)

        body = auth_client(manager).get(URL, PARAMS).json()

        assert [g["categoryName"] for g in body["categories"]] == ["Épicerie", "Zeste"]

    def _stock_up(self, site, count):
        category = CategoryFactory()
        for _ in range(count):
            stocked = ArticleFactory(category=category)
            StockLevelFactory(article=stocked, site=site, quantity=2)
            StockMovementFactory(article=stocked, site=site)

    def test_the_query_count_is_flat_with_one_article(
        self, auth_client, manager, site, django_assert_num_queries
    ):
        self._stock_up(site, 1)
        client = auth_client(manager)
        client.get(URL, PARAMS)  # warm any lazy auth/site lookups
        with django_assert_num_queries(FLAT_QUERY_COUNT):
            client.get(URL, PARAMS)

    def test_the_query_count_is_flat_with_five_articles(
        self, auth_client, manager, site, django_assert_num_queries
    ):
        self._stock_up(site, 5)
        client = auth_client(manager)
        client.get(URL, PARAMS)
        with django_assert_num_queries(FLAT_QUERY_COUNT):
            client.get(URL, PARAMS)
