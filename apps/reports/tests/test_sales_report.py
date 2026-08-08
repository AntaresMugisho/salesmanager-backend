"""The rapport des ventes.

The builder tests run on hand-built facts — no database — so they can state
awkward situations (an overpaid cancelled sale, two sales in the same second)
directly. The API tests at the end check the wiring and the wire format.
"""

from decimal import Decimal

import pytest

from apps.finance.aggregate import summarise
from apps.reports.sales import WALK_IN_LABEL, build_sales_report
from apps.reports.tests.factsbuilders import facts, line, payment, sale
from apps.reports.tests.support import GENERATED_AT, JULY, KINSHASA, PARAMS, at, dated
from apps.sales.models import Sale
from apps.sales.tests.factories import CustomerFactory, PaymentFactory, SaleLineFactory

URL = "/api/reports/sales/"


def build(**kw):
    return build_sales_report(facts(**kw), KINSHASA, *JULY, GENERATED_AT)


class TestTotals:
    def test_it_counts_completed_sales_in_the_period(self):
        result = build(sales=[sale(id="a", day=15), sale(id="b", day=20)])
        assert result["totals"]["invoice_count"] == 2

    def test_a_sale_outside_the_period_is_not_counted(self):
        result = build(sales=[sale(id="a", day=15), sale(id="b", day=3, month=6)])
        assert result["totals"]["invoice_count"] == 1

    def test_cancelled_sales_are_counted_separately(self):
        result = build(sales=[sale(id="a"), sale(id="b", status="CANCELLED")])
        assert result["totals"]["invoice_count"] == 1
        assert result["totals"]["cancelled_count"] == 1

    def test_total_ttc_covers_completed_sales_only(self):
        result = build(
            sales=[
                sale(id="a", total=11_600),
                sale(id="b", total=5_000, status="CANCELLED"),
            ],
        )
        assert result["totals"]["total_ttc"] == 11_600

    def test_discounts_sum_over_completed_sales_only(self):
        result = build(
            sales=[
                sale(id="a", discount=600),
                sale(id="b", discount=900, status="CANCELLED"),
            ],
        )
        assert result["totals"]["discounts"] == 600

    def test_the_shared_figures_come_from_summarise(self):
        """Asserted against summarise() itself, not literals: this is the
        guarantee that the report and /finances cannot disagree."""
        given = facts(
            sales=[sale(id="a", total=11_600, vat_total=1_600)],
            lines=[line(sale_id="a")],
            payments=[payment(sale_id="a", amount=5_000)],
        )
        expected = summarise(given, KINSHASA, *JULY)

        totals = build_sales_report(given, KINSHASA, *JULY, GENERATED_AT)["totals"]

        assert totals["revenueHT"] == expected["revenue"]
        assert totals["vat_collected"] == expected["vat_collected"]
        assert totals["receipts"] == expected["receipts"]
        assert totals["receivables"] == expected["receivables"]

    def test_receivables_ignore_the_range(self):
        # « à ce jour »: a debt from before the period is still a debt.
        result = build(sales=[sale(id="old", day=3, month=6, total=9_000)])
        assert result["totals"]["receivables"] == 9_000
        assert result["totals"]["invoice_count"] == 0

    def test_receipts_include_a_payment_on_a_later_cancelled_sale(self):
        # The cash moved; there is no refund entity to undo it.
        result = build(
            sales=[sale(id="a", status="CANCELLED")],
            payments=[payment(sale_id="a", amount=4_000)],
        )
        assert result["totals"]["receipts"] == 4_000


class TestInvoices:
    def test_every_in_period_sale_appears_cancelled_included(self):
        result = build(sales=[sale(id="a"), sale(id="b", status="CANCELLED")])
        assert {row["id"] for row in result["invoices"]} == {"a", "b"}

    def test_they_are_oldest_first(self):
        result = build(sales=[sale(id="late", day=20), sale(id="early", day=2)])
        assert [row["id"] for row in result["invoices"]] == ["early", "late"]

    def test_a_tie_is_broken_by_id_not_left_to_chance(self):
        first = build(sales=[sale(id="b", day=9), sale(id="a", day=9)])
        second = build(sales=[sale(id="a", day=9), sale(id="b", day=9)])
        assert [row["id"] for row in first["invoices"]] == ["a", "b"]
        assert [row["id"] for row in second["invoices"]] == ["a", "b"]

    def test_a_cancelled_sale_shows_its_payment_but_owes_nothing(self):
        result = build(
            sales=[sale(id="a", status="CANCELLED", total=10_000)],
            payments=[payment(sale_id="a", amount=3_000)],
        )
        row = result["invoices"][0]
        assert row["paid"] == 3_000
        assert row["balance"] == 0

    def test_a_partly_paid_sale_shows_the_remainder(self):
        result = build(
            sales=[sale(id="a", total=10_000)],
            payments=[payment(sale_id="a", amount=4_000)],
        )
        assert result["invoices"][0]["balance"] == 6_000

    def test_an_overpaid_sale_never_reads_as_negative(self):
        result = build(
            sales=[sale(id="a", total=10_000)],
            payments=[payment(sale_id="a", amount=12_000)],
        )
        assert result["invoices"][0]["balance"] == 0

    def test_a_walk_in_sale_is_labelled(self):
        result = build(sales=[sale(id="a", customer_name=None)])
        assert result["invoices"][0]["customer_name"] == WALK_IN_LABEL


class TestCustomers:
    def test_a_cancelled_sale_contributes_no_row(self):
        result = build(
            sales=[
                sale(
                    id="a",
                    status="CANCELLED",
                    customer_id="c1",
                    customer_name="Alice",
                )
            ],
        )
        assert result["customers"] == []

    def test_two_sales_for_one_customer_fold_into_one_row(self):
        result = build(
            sales=[
                sale(id="a", customer_id="c1", customer_name="Alice", total=10_000),
                sale(id="b", customer_id="c1", customer_name="Alice", total=5_000),
            ],
        )
        assert len(result["customers"]) == 1
        assert result["customers"][0]["invoice_count"] == 2
        assert result["customers"][0]["total"] == 15_000

    def test_rows_are_largest_total_first(self):
        result = build(
            sales=[
                sale(id="a", customer_id="c1", customer_name="Alice", total=5_000),
                sale(id="b", customer_id="c2", customer_name="Bob", total=9_000),
            ],
        )
        assert [row["customer_name"] for row in result["customers"]] == ["Bob", "Alice"]

    def test_every_walk_in_sale_folds_onto_one_row(self):
        result = build(
            sales=[
                sale(id="a", customer_id=None, total=1_000),
                sale(id="b", customer_id=None, total=2_000),
            ],
        )
        assert len(result["customers"]) == 1
        row = result["customers"][0]
        assert row["customer_id"] is None
        assert row["customer_name"] == WALK_IN_LABEL
        assert row["invoice_count"] == 2

    def test_an_overpaid_sale_cannot_offset_another_sales_debt(self):
        # Floored per sale before summing, not after.
        result = build(
            sales=[
                sale(id="a", customer_id="c1", customer_name="Alice", total=10_000),
                sale(id="b", customer_id="c1", customer_name="Alice", total=10_000),
            ],
            payments=[payment(sale_id="a", amount=20_000)],
        )
        assert result["customers"][0]["balance"] == 10_000


class TestVat:
    def test_it_groups_the_lines_of_completed_sales_only(self):
        result = build(
            sales=[sale(id="a"), sale(id="b", status="CANCELLED")],
            lines=[line(sale_id="a"), line(sale_id="b")],
        )
        assert len(result["vat"]) == 1
        assert result["vat"][0]["vat_amount"] == 1_600

    def test_rates_are_ascending(self):
        result = build(
            sales=[sale(id="a")],
            lines=[
                line(sale_id="a", vat_rate="16.00"),
                line(sale_id="a", vat_rate="0.00", vat_amount=0),
            ],
        )
        assert [row["vat_rate"] for row in result["vat"]] == [
            Decimal("0.00"),
            Decimal("16.00"),
        ]


@pytest.mark.django_db
class TestTheEndpoint:
    def test_a_cashier_is_refused(self, auth_client, cashier, site):
        assert auth_client(cashier).get(URL, PARAMS).status_code == 403

    def test_both_bounds_are_required(self, auth_client, manager, site):
        response = auth_client(manager).get(URL)
        assert response.status_code == 400
        assert set(response.json()["fieldErrors"]) == {"from", "to"}

    def test_the_totals_keys_match_the_contract_exactly(
        self, auth_client, manager, site
    ):
        """`revenueHT`, not `revenueHt`.

        The renderer camelises snake_case, which turns revenue_ht into
        revenueHt — and `SalesReportTotals.revenueHT` on the frontend then
        reads undefined and the document prints a blank cell. Caught on the
        wire, not by a unit test, because the builder's own key is internal.
        """
        body = auth_client(manager).get(URL, PARAMS).json()

        assert set(body["totals"]) == {
            "invoiceCount",
            "cancelledCount",
            "totalTtc",
            "revenueHT",
            "vatCollected",
            "discounts",
            "receipts",
            "receivables",
        }

    def test_an_empty_period_is_zeroed_not_a_404(self, auth_client, manager, site):
        response = auth_client(manager).get(URL, PARAMS)
        assert response.status_code == 200
        body = response.json()
        assert body["totals"]["invoiceCount"] == 0
        assert body["invoices"] == []
        assert body["customers"] == []
        assert body["vat"] == []

    def test_the_vat_rate_is_a_json_number_not_a_string(
        self, auth_client, manager, site
    ):
        """COERCE_DECIMAL_TO_STRING is False; this is the test that keeps it so.

        `vatRate` is typed `number` on the frontend, and a string would compare
        and sort wrongly there without ever raising.
        """
        customer = CustomerFactory()
        sale_line = SaleLineFactory(
            sale__site=site,
            sale__customer=customer,
            sale__customer_name=customer.name,
            vat_rate=Decimal("16.00"),
        )
        dated(Sale, sale_line.sale, at(15))

        body = auth_client(manager).get(URL, PARAMS).json()

        assert isinstance(body["vat"][0]["vatRate"], (int, float))
        assert not isinstance(body["vat"][0]["vatRate"], str)

    def test_a_cancelled_sale_appears_with_a_zero_balance(
        self, auth_client, manager, site
    ):
        sale_line = SaleLineFactory(sale__site=site, sale__status="CANCELLED")
        dated(Sale, sale_line.sale, at(15))
        PaymentFactory(sale=sale_line.sale, amount=2_000, paid_at=at(16))

        body = auth_client(manager).get(URL, PARAMS).json()

        row = body["invoices"][0]
        assert row["status"] == "CANCELLED"
        assert row["paid"] == 2_000
        assert row["balance"] == 0
