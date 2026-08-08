"""Margin by article and by category.

The snapshot rule is the one worth reading twice: a renamed article must not
rewrite what a past period says was sold, so names come from the sale line,
never from the catalogue.
"""

import pytest

from apps.finance.aggregate import line_margin, line_revenue_ht, summarise
from apps.reports.profitability import build_profitability_report
from apps.reports.tests.factsbuilders import facts, line, sale
from apps.reports.tests.support import GENERATED_AT, JULY, KINSHASA, PARAMS, at, dated
from apps.sales.models import Sale
from apps.sales.tests.factories import SaleLineFactory

URL = "/api/reports/profitability/"

CATALOGUE = {
    "a1": {
        "article_id": "a1",
        "sku": "ART-1",
        "name": "Riz (catalogue)",
        "unit": "PIECE",
        "purchase_price": 800,
        "category_id": "cat1",
        "category_name": "Épicerie",
    },
    "a2": {
        "article_id": "a2",
        "sku": "ART-2",
        "name": "Savon (catalogue)",
        "unit": "PIECE",
        "purchase_price": 500,
        "category_id": "cat1",
        "category_name": "Épicerie",
    },
    "a3": {
        "article_id": "a3",
        "sku": "ART-3",
        "name": "Jus",
        "unit": "PIECE",
        "purchase_price": 300,
        "category_id": "cat2",
        "category_name": "Boissons",
    },
}


def build(catalogue=None, **kw):
    return build_profitability_report(
        facts(**kw), catalogue or CATALOGUE, KINSHASA, *JULY, GENERATED_AT
    )


class TestArticleRows:
    def test_lines_fold_by_article_across_sales(self):
        result = build(
            sales=[sale(id="s1"), sale(id="s2")],
            lines=[
                line(sale_id="s1", article_id="a1", quantity=2),
                line(sale_id="s2", article_id="a1", quantity=3),
            ],
        )
        assert len(result["articles"]) == 1
        assert result["articles"][0]["quantity"] == 5

    def test_revenue_and_margin_come_from_the_shared_line_functions(self):
        one = line(sale_id="s1", article_id="a1")
        result = build(sales=[sale(id="s1")], lines=[one])

        row = result["articles"][0]
        assert row["revenue"] == line_revenue_ht(one)
        assert row["margin"] == line_margin(one)

    def test_cogs_is_quantity_times_the_cost_snapshot(self):
        result = build(
            sales=[sale(id="s1")],
            lines=[line(sale_id="s1", article_id="a1", quantity=3, unit_cost=800)],
        )
        assert result["articles"][0]["cogs"] == 2_400

    def test_the_name_and_sku_come_from_the_line_not_the_catalogue(self):
        """A renamed article must not rewrite a past period.

        The catalogue here says "Riz (catalogue)"; the line snapshot says
        "Riz (au moment de la vente)". The document must print the snapshot.
        """
        result = build(
            sales=[sale(id="s1")],
            lines=[
                line(
                    sale_id="s1",
                    article_id="a1",
                    article_name="Riz (au moment de la vente)",
                    article_sku="ART-ANCIEN",
                )
            ],
        )
        row = result["articles"][0]
        assert row["name"] == "Riz (au moment de la vente)"
        assert row["sku"] == "ART-ANCIEN"

    def test_they_are_highest_margin_first(self):
        result = build(
            sales=[sale(id="s1")],
            lines=[
                line(sale_id="s1", article_id="a1", unit_cost=5_000),
                line(sale_id="s1", article_id="a3", unit_cost=1_000),
            ],
        )
        margins = [row["margin"] for row in result["articles"]]
        assert margins == sorted(margins, reverse=True)


class TestCategoryRows:
    def test_articles_aggregate_into_their_category(self):
        result = build(
            sales=[sale(id="s1")],
            lines=[
                line(sale_id="s1", article_id="a1"),
                line(sale_id="s1", article_id="a2"),
            ],
        )
        assert len(result["categories"]) == 1
        assert result["categories"][0]["name"] == "Épicerie"
        assert result["categories"][0]["quantity"] == 4

    def test_the_category_name_does_come_from_the_catalogue(self):
        # The one thing the catalogue is consulted for.
        result = build(sales=[sale(id="s1")], lines=[line(sale_id="s1", article_id="a3")])
        assert result["categories"][0]["name"] == "Boissons"

    def test_a_category_row_has_no_sku(self):
        result = build(sales=[sale(id="s1")], lines=[line(sale_id="s1")])
        assert result["categories"][0]["sku"] is None


class TestExclusions:
    def test_cancelled_sales_are_excluded(self):
        result = build(
            sales=[sale(id="s1", status="CANCELLED")],
            lines=[line(sale_id="s1")],
        )
        assert result["articles"] == []
        assert result["totals"]["revenue"] == 0

    def test_sales_outside_the_range_are_excluded(self):
        result = build(
            sales=[sale(id="s1", day=3, month=6)],
            lines=[line(sale_id="s1")],
        )
        assert result["articles"] == []


class TestLowMargin:
    def test_it_holds_rows_at_or_below_zero_worst_first(self):
        result = build(
            sales=[sale(id="s1")],
            lines=[
                # revenue 10 000, cost 2 x 6 000 -> margin -2 000
                line(sale_id="s1", article_id="a1", unit_cost=6_000),
                # revenue 10 000, cost 2 x 9 000 -> margin -8 000
                line(sale_id="s1", article_id="a2", unit_cost=9_000),
                line(sale_id="s1", article_id="a3", unit_cost=1_000),
            ],
        )
        assert [row["margin"] for row in result["low_margin"]] == [-8_000, -2_000]

    def test_a_zero_margin_row_is_included(self):
        # The rule is `<= 0`, not `< 0`: breaking even is worth showing.
        result = build(
            sales=[sale(id="s1")],
            lines=[line(sale_id="s1", article_id="a1", quantity=2, unit_cost=5_000)],
        )
        assert result["articles"][0]["margin"] == 0
        assert len(result["low_margin"]) == 1


class TestMarginRate:
    def test_it_is_zero_when_revenue_is_zero(self):
        result = build()
        assert result["totals"]["margin_rate"] == 0

    def test_it_is_not_rounded(self):
        """Python and JavaScript agree bit-for-bit only if neither rounds.

        Revenue 3, margin 1 -> 100/3, which has no exact decimal form. A
        rounded implementation would return 33.33 and disagree with the browser.
        """
        result = build(
            sales=[sale(id="s1", total=3, vat_total=0)],
            lines=[
                line(
                    sale_id="s1",
                    article_id="a1",
                    quantity=1,
                    line_total=3,
                    discount_share=0,
                    vat_amount=0,
                    unit_cost=2,
                )
            ],
        )
        rate = result["articles"][0]["margin_rate"]
        assert rate == pytest.approx(100 / 3)
        assert rate != 33.33

    def test_the_total_rate_comes_from_the_totals_not_an_average_of_rows(self):
        result = build(
            sales=[sale(id="s1")],
            lines=[
                line(sale_id="s1", article_id="a1", unit_cost=1_000),
                line(sale_id="s1", article_id="a3", unit_cost=4_000),
            ],
        )
        totals = result["totals"]
        assert totals["margin_rate"] == pytest.approx(
            (totals["margin"] / totals["revenue"]) * 100
        )


class TestTotalsAgreeWithTheResultReport:
    def test_they_equal_summarise_for_the_same_facts(self):
        """The roll-up guarantee, asserted directly.

        Both start from `line_revenue_ht` and `line_margin`, so this holds by
        construction — but only until someone 'optimises' one of them.
        """
        given = facts(
            sales=[sale(id="s1", total=11_600, vat_total=1_600)],
            lines=[line(sale_id="s1", article_id="a1")],
        )
        summary = summarise(given, KINSHASA, *JULY)
        totals = build_profitability_report(
            given, CATALOGUE, KINSHASA, *JULY, GENERATED_AT
        )["totals"]

        assert totals["revenue"] == summary["revenue"]
        assert totals["cogs"] == summary["cogs"]
        assert totals["margin"] == summary["gross_margin"]


@pytest.mark.django_db
class TestTheEndpoint:
    def test_a_cashier_is_refused(self, auth_client, cashier, site):
        assert auth_client(cashier).get(URL, PARAMS).status_code == 403

    def test_both_bounds_are_required(self, auth_client, manager, site):
        response = auth_client(manager).get(URL)
        assert response.status_code == 400
        assert set(response.json()["fieldErrors"]) == {"from", "to"}

    def test_an_empty_period_is_zeroed_not_a_404(self, auth_client, manager, site):
        response = auth_client(manager).get(URL, PARAMS)
        assert response.status_code == 200
        body = response.json()
        assert body["articles"] == []
        assert body["categories"] == []
        assert body["lowMargin"] == []
        assert body["totals"]["revenue"] == 0
        assert body["totals"]["marginRate"] == 0

    def test_it_agrees_with_the_result_report_over_the_wire(
        self, auth_client, manager, site
    ):
        # The sale header must agree with its lines, as `create_sale`
        # guarantees for real data: summarise() derives revenue from the header
        # (total - vat_total) and this report derives it from the lines. A
        # factory that sets only the line leaves the two describing different
        # sales, and the mismatch looks like a code bug.
        sale_line = SaleLineFactory(
            sale__site=site,
            sale__total=11_600,
            sale__vat_total=1_600,
            quantity=2,
            unit_cost=3_000,
            line_total=11_600,
            vat_amount=1_600,
        )
        dated(Sale, sale_line.sale, at(15))
        client = auth_client(manager)

        profitability = client.get(URL, PARAMS).json()
        result = client.get("/api/reports/result/", PARAMS).json()

        assert profitability["totals"]["revenue"] == result["summary"]["revenue"]
        assert profitability["totals"]["cogs"] == result["summary"]["cogs"]
        assert profitability["totals"]["margin"] == result["summary"]["grossMargin"]
        # Guard: all-zero would satisfy the three assertions above.
        assert profitability["totals"]["revenue"] > 0
