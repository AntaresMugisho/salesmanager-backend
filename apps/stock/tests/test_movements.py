"""Movement endpoints."""

import uuid
from datetime import datetime, timezone as dt_timezone

import pytest

from apps.catalogue.tests.factories import ArticleFactory
from apps.stock.models import StockLevel, StockMovement
from apps.stock.tests.factories import StockLevelFactory, StockMovementFactory

pytestmark = pytest.mark.django_db

URL = "/api/stock/movements/"


class TestCreate:
    def test_a_manager_can_post_an_in_movement(self, auth_client, manager, site):
        article = ArticleFactory()
        StockLevelFactory(article=article, site=site, quantity=5)

        response = auth_client(manager).post(
            URL,
            {
                "articleId": str(article.id),
                "type": "IN",
                "reason": "PURCHASE",
                "quantity": 10,
                "unitCost": 1200,
                "reference": "BL-42",
                "note": "Livraison du matin",
            },
            format="json",
        )

        assert response.status_code == 201
        assert response.json()["quantityBefore"] == 5
        assert response.json()["quantityAfter"] == 15
        assert StockLevel.objects.get().quantity == 15

    def test_the_payload_matches_the_frontend_type(self, auth_client, manager, site):
        article = ArticleFactory()
        response = auth_client(manager).post(
            URL,
            {
                "articleId": str(article.id),
                "type": "IN",
                "reason": "PURCHASE",
                "quantity": 3,
                "unitCost": None,
                "reference": None,
                "note": None,
            },
            format="json",
        )

        assert set(response.json()) == {
            "id",
            "articleId",
            "article",
            "siteId",
            "type",
            "reason",
            "quantity",
            "quantityBefore",
            "quantityAfter",
            "unitCost",
            "reference",
            "note",
            "transactionId",
            "saleId",
            "userId",
            "userName",
            "createdAt",
        }
        assert set(response.json()["article"]) == {"id", "sku", "name", "unit"}

    def test_transaction_id_and_sale_id_are_null(self, auth_client, manager, site):
        """No columns yet — sub-projects 3 and 4 add them. The keys must still
        be present, because the frontend's StockMovement type requires them."""
        article = ArticleFactory()
        response = auth_client(manager).post(
            URL,
            {
                "articleId": str(article.id),
                "type": "IN",
                "reason": "PURCHASE",
                "quantity": 1,
            },
            format="json",
        )
        assert response.json()["transactionId"] is None
        assert response.json()["saleId"] is None

    def test_insufficient_stock_is_400_on_quantity(self, auth_client, manager, site):
        article = ArticleFactory()
        StockLevelFactory(article=article, site=site, quantity=2)

        response = auth_client(manager).post(
            URL,
            {
                "articleId": str(article.id),
                "type": "OUT",
                "reason": "SALE",
                "quantity": 5,
            },
            format="json",
        )

        assert response.status_code == 400
        assert response.json()["fieldErrors"]["quantity"] == [
            "Stock insuffisant : 2 unité(s) disponible(s) actuellement."
        ]

    def test_a_negative_quantity_is_rejected(self, auth_client, manager, site):
        article = ArticleFactory()
        response = auth_client(manager).post(
            URL,
            {
                "articleId": str(article.id),
                "type": "IN",
                "reason": "PURCHASE",
                "quantity": -1,
            },
            format="json",
        )
        assert response.status_code == 400
        assert "quantity" in response.json()["fieldErrors"]

    def test_zero_is_rejected_for_in_and_out(self, auth_client, manager, site):
        article = ArticleFactory()
        response = auth_client(manager).post(
            URL,
            {
                "articleId": str(article.id),
                "type": "IN",
                "reason": "PURCHASE",
                "quantity": 0,
            },
            format="json",
        )
        assert response.status_code == 400
        assert response.json()["fieldErrors"]["quantity"] == [
            "La quantité doit être supérieure à zéro."
        ]

    def test_zero_is_allowed_for_an_adjustment(self, auth_client, manager, site):
        """Counting a shelf and finding it empty is a legitimate adjustment."""
        article = ArticleFactory()
        StockLevelFactory(article=article, site=site, quantity=5)

        response = auth_client(manager).post(
            URL,
            {
                "articleId": str(article.id),
                "type": "ADJUSTMENT",
                "reason": "COUNT_CORRECTION",
                "quantity": 0,
            },
            format="json",
        )

        assert response.status_code == 201
        assert response.json()["quantityAfter"] == 0

    def test_an_unknown_article_is_400(self, auth_client, manager, site):
        response = auth_client(manager).post(
            URL,
            {
                "articleId": str(uuid.uuid4()),
                "type": "IN",
                "reason": "PURCHASE",
                "quantity": 1,
            },
            format="json",
        )
        assert response.status_code == 400
        assert "articleId" in response.json()["fieldErrors"]

    def test_transaction_id_carries_a_value_for_a_line(
        self, auth_client, manager, site
    ):
        """Replaces the hardcoded null sub-project 2 shipped. `saleId` keeps
        its placeholder until sub-project 4."""
        from apps.stock.services import apply_movement
        from apps.stock.tests.factories import StockTransactionFactory

        header = StockTransactionFactory(user=manager)
        article = ArticleFactory()
        apply_movement(
            article=article,
            site=site,
            type="IN",
            reason="PURCHASE",
            quantity=5,
            user=manager,
            stock_transaction=header,
        )

        row = auth_client(manager).get(URL).json()["results"][0]

        assert row["transactionId"] == str(header.id)
        assert row["saleId"] is None

    def test_sale_id_carries_a_value_for_a_sale_line(
        self, auth_client, manager, site
    ):
        """The last hardcoded null is gone. A movement carries at most one of
        transactionId and saleId."""
        from apps.sales.services import create_sale
        from apps.stock.tests.factories import StockLevelFactory

        article = ArticleFactory()
        StockLevelFactory(article=article, site=site, quantity=50)
        sale = create_sale(
            lines=[{"article": article, "quantity": 2, "unit_price": 5_000}],
            user=manager,
            site=site,
        )

        row = auth_client(manager).get(URL).json()["results"][0]

        assert row["saleId"] == str(sale.id)
        assert row["transactionId"] is None

    def test_a_cashier_may_not_post(self, auth_client, cashier, site):
        article = ArticleFactory()
        response = auth_client(cashier).post(
            URL,
            {
                "articleId": str(article.id),
                "type": "IN",
                "reason": "PURCHASE",
                "quantity": 1,
            },
            format="json",
        )
        assert response.status_code == 403


class TestList:
    def test_newest_first(self, auth_client, cashier, site, owner):
        first = StockMovementFactory(site=site, user=owner)
        second = StockMovementFactory(site=site, user=owner)

        response = auth_client(cashier).get(URL)

        assert [r["id"] for r in response.json()["results"]] == [
            str(second.id),
            str(first.id),
        ]

    def test_filter_by_article(self, auth_client, cashier, site, owner):
        wanted = ArticleFactory()
        StockMovementFactory(site=site, user=owner, article=wanted)
        StockMovementFactory(site=site, user=owner)

        response = auth_client(cashier).get(f"{URL}?articleId={wanted.id}")
        assert response.json()["count"] == 1

    def test_filter_by_sale_id(self, auth_client, cashier, site, owner):
        from apps.sales.services import create_sale

        article = ArticleFactory()
        StockLevelFactory(article=article, site=site, quantity=50)
        wanted = create_sale(
            lines=[{"article": article, "quantity": 2, "unit_price": 5_000}],
            user=owner,
            site=site,
        )
        create_sale(
            lines=[{"article": article, "quantity": 1, "unit_price": 5_000}],
            user=owner,
            site=site,
        )
        StockMovementFactory(site=site, user=owner)

        response = auth_client(cashier).get(f"{URL}?saleId={wanted.id}")

        assert response.json()["count"] == 1
        assert response.json()["results"][0]["saleId"] == str(wanted.id)

    def test_filter_by_type_and_reason(self, auth_client, cashier, site, owner):
        StockMovementFactory(site=site, user=owner, type="IN", reason="PURCHASE")
        StockMovementFactory(site=site, user=owner, type="OUT", reason="DAMAGE")
        client = auth_client(cashier)

        assert client.get(f"{URL}?type=OUT").json()["count"] == 1
        assert client.get(f"{URL}?reason=DAMAGE").json()["count"] == 1

    def test_search_covers_article_name_sku_and_reference(
        self, auth_client, cashier, site, owner
    ):
        article = ArticleFactory(name="Sucre blanc", sku="EPI-001")
        StockMovementFactory(site=site, user=owner, article=article, reference="BL-42")
        StockMovementFactory(site=site, user=owner)
        client = auth_client(cashier)

        assert client.get(f"{URL}?search=sucre").json()["count"] == 1
        assert client.get(f"{URL}?search=EPI-001").json()["count"] == 1
        assert client.get(f"{URL}?search=BL-42").json()["count"] == 1

    @pytest.mark.parametrize(
        ("param", "value"), [("type", "SIDEWAYS"), ("reason", "PARCE_QUE")]
    )
    def test_an_invalid_filter_value_is_400(
        self, auth_client, cashier, site, param, value
    ):
        response = auth_client(cashier).get(f"{URL}?{param}={value}")
        assert response.status_code == 400
        assert param in response.json()["fieldErrors"]

    def test_the_list_query_count_is_flat(
        self, auth_client, cashier, site, owner, django_assert_num_queries
    ):
        for _ in range(10):
            StockMovementFactory(site=site, user=owner)

        client = auth_client(cashier)
        client.get(URL)

        with django_assert_num_queries(3):
            response = client.get(f"{URL}?pageSize=10")

        assert len(response.json()["results"]) == 10


class TestDateBounds:
    """Kinshasa is UTC+1. A movement at 00:30 local on 2 July is 23:30 UTC on
    1 July — a UTC implementation files it under the wrong day, and these
    tests are the only thing that catches it.

    The timezone is pinned by a fixture rather than `@override_settings` on
    the class: that decorator only accepts SimpleTestCase subclasses, and
    silently refuses a plain pytest class.
    """

    @pytest.fixture(autouse=True)
    def _kinshasa(self, settings):
        settings.SHOP_TIME_ZONE = "Africa/Kinshasa"

    def _movement_at(self, instant, site, owner):
        movement = StockMovementFactory(site=site, user=owner)
        StockMovement.objects.filter(pk=movement.pk).update(created_at=instant)
        return movement

    def test_date_from_includes_a_movement_early_in_the_local_morning(
        self, auth_client, cashier, site, owner
    ):
        self._movement_at(
            datetime(2026, 7, 1, 23, 30, tzinfo=dt_timezone.utc), site, owner
        )  # 2 July, 00:30 in Kinshasa

        response = auth_client(cashier).get(f"{URL}?dateFrom=2026-07-02")

        assert response.json()["count"] == 1

    def test_date_from_excludes_the_previous_local_day(
        self, auth_client, cashier, site, owner
    ):
        self._movement_at(
            datetime(2026, 7, 1, 22, 30, tzinfo=dt_timezone.utc), site, owner
        )  # 1 July, 23:30 in Kinshasa

        response = auth_client(cashier).get(f"{URL}?dateFrom=2026-07-02")

        assert response.json()["count"] == 0

    def test_date_to_is_inclusive_of_the_whole_local_day(
        self, auth_client, cashier, site, owner
    ):
        self._movement_at(
            datetime(2026, 7, 2, 22, 30, tzinfo=dt_timezone.utc), site, owner
        )  # 2 July, 23:30 in Kinshasa

        response = auth_client(cashier).get(f"{URL}?dateTo=2026-07-02")

        assert response.json()["count"] == 1

    def test_a_malformed_date_is_400(self, auth_client, cashier, site):
        response = auth_client(cashier).get(f"{URL}?dateFrom=le-2-juillet")
        assert response.status_code == 400
        assert "dateFrom" in response.json()["fieldErrors"]
