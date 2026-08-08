"""The three finance reads, end to end."""

from datetime import datetime, timezone as dt_timezone

import pytest

from apps.catalogue.tests.factories import ArticleFactory
from apps.expenses.tests.factories import ExpenseFactory
from apps.sales.models import Sale
from apps.sales.services import create_sale
from apps.sales.tests.factories import PaymentFactory
from apps.stock.tests.factories import StockLevelFactory

pytestmark = pytest.mark.django_db

SUMMARY = "/api/finance/summary/"
SERIES = "/api/finance/series/"
BREAKDOWN = "/api/finance/breakdown/"
JULY = "?from=2026-07-01&to=2026-07-31"


def stocked(site, quantity=1000, **kwargs):
    article = ArticleFactory(**kwargs)
    StockLevelFactory(article=article, site=site, quantity=quantity)
    return article


def sold(site, user, unit_price=11_600, quantity=1, day=15, **kwargs):
    sale = create_sale(
        lines=[
            {"article": stocked(site), "quantity": quantity, "unit_price": unit_price}
        ],
        user=user,
        site=site,
        **kwargs,
    )
    Sale.objects.filter(pk=sale.pk).update(
        created_at=datetime(2026, 7, day, 12, tzinfo=dt_timezone.utc)
    )
    sale.refresh_from_db()
    return sale


class TestSummary:
    def test_the_payload_matches_the_frontend_type(self, auth_client, manager, site):
        response = auth_client(manager).get(f"{SUMMARY}{JULY}")

        assert response.status_code == 200
        assert set(response.json()) == {
            "revenue",
            "cogs",
            "grossMargin",
            "marginRate",
            "expenses",
            "netResult",
            "vatCollected",
            "receipts",
            "purchaseDisbursements",
            "disbursements",
            "cashBalance",
            "receivables",
            "purchasesWithoutCost",
        }

    def test_an_empty_period_is_all_zeros(self, auth_client, manager, site):
        payload = auth_client(manager).get(f"{SUMMARY}{JULY}").json()
        assert payload["revenue"] == 0
        assert payload["marginRate"] == 0
        assert payload["receivables"] == 0

    def test_a_sale_reaches_the_summary(self, auth_client, manager, site):
        sold(site, manager, unit_price=11_600, quantity=1)

        payload = auth_client(manager).get(f"{SUMMARY}{JULY}").json()

        # 11 600 TTC at the factory's 16% -> 1 600 VAT, 10 000 HT.
        assert payload["revenue"] == 10_000
        assert payload["vatCollected"] == 1_600

    def test_an_expense_reaches_the_summary(self, auth_client, manager, site):
        from apps.expenses.models import Expense

        expense = ExpenseFactory(site=site, user=manager, amount=2_500)
        Expense.objects.filter(pk=expense.pk).update(
            spent_at=datetime(2026, 7, 10, 12, tzinfo=dt_timezone.utc)
        )

        payload = auth_client(manager).get(f"{SUMMARY}{JULY}").json()

        assert payload["expenses"] == 2_500

    def test_the_opening_stock_movement_counts_as_a_purchase(
        self, auth_client, manager, site
    ):
        """An IN/PURCHASE movement is a purchase whether it came from a
        transaction or from an article's opening balance."""
        from apps.stock.models import StockMovement
        from apps.stock.services import apply_movement

        article = ArticleFactory()
        movement = apply_movement(
            article=article,
            site=site,
            type="IN",
            reason="PURCHASE",
            quantity=10,
            unit_cost=800,
            user=manager,
        )
        StockMovement.objects.filter(pk=movement.pk).update(
            created_at=datetime(2026, 7, 5, 12, tzinfo=dt_timezone.utc)
        )

        payload = auth_client(manager).get(f"{SUMMARY}{JULY}").json()

        assert payload["purchaseDisbursements"] == 8_000
        assert payload["purchasesWithoutCost"] == 0

    def test_margin_rate_is_a_float_not_a_string(self, auth_client, manager, site):
        sold(site, manager)
        payload = auth_client(manager).get(f"{SUMMARY}{JULY}").json()
        assert isinstance(payload["marginRate"], float)

    def test_receivables_ignore_the_period(self, auth_client, manager, site):
        """« à ce jour » — a January sale still shows in a July request."""
        sale = sold(site, manager, unit_price=10_000)
        Sale.objects.filter(pk=sale.pk).update(
            created_at=datetime(2026, 1, 15, 12, tzinfo=dt_timezone.utc)
        )

        payload = auth_client(manager).get(f"{SUMMARY}{JULY}").json()

        assert payload["revenue"] == 0
        assert payload["receivables"] == 10_000


class TestSeries:
    def test_the_payload_matches_the_frontend_type(self, auth_client, manager, site):
        response = auth_client(manager).get(f"{SERIES}{JULY}")

        assert response.status_code == 200
        assert set(response.json()) == {"granularity", "buckets"}
        assert set(response.json()["buckets"][0]) == {
            "key",
            "label",
            "revenue",
            "cogs",
            "margin",
            "receipts",
            "disbursements",
            "cumulativeCash",
        }

    def test_july_yields_thirty_one_daily_buckets(self, auth_client, manager, site):
        payload = auth_client(manager).get(f"{SERIES}{JULY}").json()
        assert payload["granularity"] == "DAY"
        assert len(payload["buckets"]) == 31

    def test_a_year_yields_twelve_monthly_buckets(self, auth_client, manager, site):
        payload = (
            auth_client(manager).get(f"{SERIES}?from=2026-01-01&to=2026-12-31").json()
        )
        assert payload["granularity"] == "MONTH"
        assert len(payload["buckets"]) == 12
        assert payload["buckets"][0]["label"] == "janv. 2026"

    def test_the_labels_are_french(self, auth_client, manager, site):
        payload = auth_client(manager).get(f"{SERIES}{JULY}").json()
        assert payload["buckets"][0]["label"] == "1 juil."
        assert payload["buckets"][30]["label"] == "31 juil."


class TestBreakdown:
    def test_the_payload_matches_the_frontend_type(self, auth_client, manager, site):
        response = auth_client(manager).get(f"{BREAKDOWN}{JULY}")

        assert response.status_code == 200
        assert set(response.json()) == {"expenses", "topArticles", "unpaidSales"}

    def test_an_unpaid_sale_is_listed_with_camel_case_keys(
        self, auth_client, manager, site
    ):
        sale = sold(site, manager, unit_price=10_000)

        rows = auth_client(manager).get(f"{BREAKDOWN}{JULY}").json()["unpaidSales"]

        assert len(rows) == 1
        assert set(rows[0]) == {
            "id",
            "reference",
            "customerName",
            "createdAt",
            "total",
            "balance",
        }
        assert rows[0]["balance"] == sale.total

    def test_a_paid_sale_drops_off_the_unpaid_list(self, auth_client, manager, site):
        sale = sold(site, manager)
        PaymentFactory(sale=sale, user=manager, amount=sale.total)

        rows = auth_client(manager).get(f"{BREAKDOWN}{JULY}").json()["unpaidSales"]

        assert rows == []

    def test_top_article_rows_carry_the_expected_keys(self, auth_client, manager, site):
        sold(site, manager)

        rows = auth_client(manager).get(f"{BREAKDOWN}{JULY}").json()["topArticles"]

        assert set(rows[0]) == {
            "articleId",
            "articleName",
            "articleSku",
            "quantity",
            "revenue",
            "margin",
        }

    def test_expense_rows_carry_a_share(self, auth_client, manager, site):
        from apps.expenses.models import Expense

        expense = ExpenseFactory(site=site, user=manager, amount=1_000)
        Expense.objects.filter(pk=expense.pk).update(
            spent_at=datetime(2026, 7, 10, 12, tzinfo=dt_timezone.utc)
        )

        rows = auth_client(manager).get(f"{BREAKDOWN}{JULY}").json()["expenses"]

        assert set(rows[0]) == {"category", "amount", "share"}
        assert rows[0]["share"] == 100.0


class TestRangeValidation:
    @pytest.mark.parametrize("url", [SUMMARY, SERIES, BREAKDOWN])
    def test_a_missing_range_is_400(self, auth_client, manager, site, url):
        response = auth_client(manager).get(url)
        assert response.status_code == 400
        assert "from" in response.json()["fieldErrors"]

    @pytest.mark.parametrize("url", [SUMMARY, SERIES, BREAKDOWN])
    def test_an_inverted_range_is_400(self, auth_client, manager, site, url):
        response = auth_client(manager).get(f"{url}?from=2026-07-31&to=2026-07-01")
        assert response.status_code == 400
        assert response.json()["fieldErrors"]["from"] == [
            "La date de début doit précéder la date de fin."
        ]

    @pytest.mark.parametrize("url", [SUMMARY, SERIES, BREAKDOWN])
    def test_a_malformed_date_is_400(self, auth_client, manager, site, url):
        response = auth_client(manager).get(f"{url}?from=juillet&to=2026-07-31")
        assert response.status_code == 400
        assert "from" in response.json()["fieldErrors"]

    def test_a_single_day_range_is_valid(self, auth_client, manager, site):
        response = auth_client(manager).get(f"{SUMMARY}?from=2026-07-01&to=2026-07-01")
        assert response.status_code == 200


class TestPermissions:
    @pytest.mark.parametrize("url", [SUMMARY, SERIES, BREAKDOWN])
    def test_a_cashier_is_refused(self, auth_client, cashier, site, url):
        response = auth_client(cashier).get(f"{url}{JULY}")
        assert response.status_code == 403
        assert response.json()["code"] == "permission_denied"

    @pytest.mark.parametrize("url", [SUMMARY, SERIES, BREAKDOWN])
    def test_an_owner_may_read(self, auth_client, owner, site, url):
        assert auth_client(owner).get(f"{url}{JULY}").status_code == 200

    @pytest.mark.parametrize("url", [SUMMARY, SERIES, BREAKDOWN])
    def test_anonymous_is_401(self, api_client, site, url):
        response = api_client.get(f"{url}{JULY}")
        assert response.status_code == 401


class TestQueryCount:
    def test_the_summary_reads_a_fixed_number_of_tables(
        self, auth_client, manager, site, django_assert_num_queries
    ):
        for day in range(1, 6):
            sold(site, manager, day=day)

        client = auth_client(manager)
        client.get(f"{SUMMARY}{JULY}")

        # 1 user, 1 site, then one read per fact table: sales, lines,
        # payments, expenses, purchases.
        with django_assert_num_queries(7):
            response = client.get(f"{SUMMARY}{JULY}")

        assert response.status_code == 200
