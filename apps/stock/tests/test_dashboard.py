"""Low-stock and dashboard reads."""

from datetime import datetime, timezone as dt_timezone

import pytest

from apps.catalogue.tests.factories import ArticleFactory
from apps.stock.models import StockMovement
from apps.stock.tests.factories import StockLevelFactory, StockMovementFactory

pytestmark = pytest.mark.django_db

LOW_STOCK_URL = "/api/stock/low-stock/"
DASHBOARD_URL = "/api/stock/dashboard/"


def stocked(site, quantity, threshold, **article_kwargs):
    article = ArticleFactory(**article_kwargs)
    StockLevelFactory(
        article=article, site=site, quantity=quantity, reorder_threshold=threshold
    )
    return article


class TestLowStock:
    def test_returns_low_and_out_of_stock_only(self, auth_client, cashier, site):
        stocked(site, 0, 10)  # OUT_OF_STOCK
        stocked(site, 5, 10)  # LOW
        stocked(site, 50, 10)  # IN_STOCK

        response = auth_client(cashier).get(LOW_STOCK_URL)

        assert response.status_code == 200
        assert response.json()["count"] == 2

    def test_archived_articles_never_count(self, auth_client, cashier, site):
        """`isLowStockArticle` checks isActive first. An archived article is
        not something to reorder."""
        stocked(site, 0, 10, is_active=False)

        response = auth_client(cashier).get(LOW_STOCK_URL)

        assert response.json()["count"] == 0

    def test_ruptures_first_then_ascending_quantity(self, auth_client, cashier, site):
        stocked(site, 8, 10, name="Huit")
        stocked(site, 0, 10, name="Rupture")
        stocked(site, 3, 10, name="Trois")

        response = auth_client(cashier).get(LOW_STOCK_URL)

        assert [r["name"] for r in response.json()["results"]] == [
            "Rupture",
            "Trois",
            "Huit",
        ]

    def test_the_payload_is_the_article_shape(self, auth_client, cashier, site):
        stocked(site, 0, 10)
        row = auth_client(cashier).get(LOW_STOCK_URL).json()["results"][0]
        assert "stock" in row
        assert set(row["stock"]) == {"siteId", "quantity", "reorderThreshold", "status"}

    def test_search_is_supported(self, auth_client, cashier, site):
        stocked(site, 0, 10, name="Sucre", sku="EPI-1")
        stocked(site, 0, 10, name="Farine", sku="EPI-2")

        response = auth_client(cashier).get(f"{LOW_STOCK_URL}?search=sucre")

        assert response.json()["count"] == 1


class TestDashboard:
    def test_the_payload_matches_the_frontend_type(self, auth_client, cashier, site):
        response = auth_client(cashier).get(DASHBOARD_URL)

        assert response.status_code == 200
        assert set(response.json()) == {
            "articleCount",
            "stockValue",
            "lowStockCount",
            "movementsToday",
        }

    def test_article_count_excludes_archived(self, auth_client, cashier, site):
        ArticleFactory(is_active=True)
        ArticleFactory(is_active=True)
        ArticleFactory(is_active=False)

        response = auth_client(cashier).get(DASHBOARD_URL)

        assert response.json()["articleCount"] == 2

    def test_stock_value_is_quantity_times_purchase_price(
        self, auth_client, cashier, site
    ):
        stocked(site, 10, 0, purchase_price=1500)
        stocked(site, 4, 0, purchase_price=250)

        response = auth_client(cashier).get(DASHBOARD_URL)

        assert response.json()["stockValue"] == 10 * 1500 + 4 * 250

    def test_stock_value_counts_archived_articles(self, auth_client, cashier, site):
        """`getDashboardStats` sums every level without checking isActive —
        archived stock is still stock the shop owns."""
        stocked(site, 10, 0, purchase_price=1000, is_active=False)

        response = auth_client(cashier).get(DASHBOARD_URL)

        assert response.json()["stockValue"] == 10_000

    def test_low_stock_count_agrees_with_the_low_stock_list(
        self, auth_client, cashier, site
    ):
        stocked(site, 0, 10)
        stocked(site, 5, 10)
        stocked(site, 50, 10)
        stocked(site, 0, 10, is_active=False)

        client = auth_client(cashier)
        dashboard = client.get(DASHBOARD_URL)
        listing = client.get(LOW_STOCK_URL)

        assert dashboard.json()["lowStockCount"] == listing.json()["count"] == 2

    def test_movements_today_uses_the_local_day(
        self, auth_client, cashier, site, owner, settings
    ):
        from unittest import mock

        from django.utils import timezone as dj_timezone

        settings.SHOP_TIME_ZONE = "Africa/Kinshasa"
        now = datetime(2026, 7, 2, 8, 0, tzinfo=dt_timezone.utc)  # 09:00 local

        today = StockMovementFactory(site=site, user=owner)
        yesterday = StockMovementFactory(site=site, user=owner)
        StockMovement.objects.filter(pk=today.pk).update(
            created_at=datetime(2026, 7, 1, 23, 30, tzinfo=dt_timezone.utc)
        )  # 2 July 00:30 local — today
        StockMovement.objects.filter(pk=yesterday.pk).update(
            created_at=datetime(2026, 7, 1, 22, 30, tzinfo=dt_timezone.utc)
        )  # 1 July 23:30 local — yesterday

        with mock.patch.object(dj_timezone, "now", return_value=now):
            response = auth_client(cashier).get(DASHBOARD_URL)

        assert response.json()["movementsToday"] == 1

    def test_an_empty_shop_returns_zeros_not_nulls(self, auth_client, cashier, site):
        response = auth_client(cashier).get(DASHBOARD_URL)
        assert response.json() == {
            "articleCount": 0,
            "stockValue": 0,
            "lowStockCount": 0,
            "movementsToday": 0,
        }

    def test_a_cashier_may_read_the_dashboard(self, auth_client, cashier, site):
        assert auth_client(cashier).get(DASHBOARD_URL).status_code == 200
