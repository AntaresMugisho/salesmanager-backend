"""Finance aggregation, ported from features/finance/lib/aggregate.ts.

No Django, no database — the facts are hand-built dicts. The last class runs
the frontend's own implementation in Node over randomised facts and diffs.
"""

import json
import random
import shutil
import subprocess
from datetime import date, datetime, timezone as dt_timezone
from zoneinfo import ZoneInfo

import pytest

from apps.finance.aggregate import (
    TOP_ARTICLE_COUNT,
    build_breakdown,
    bucketise,
    line_margin,
    line_revenue_ht,
    margin_rate,
    paid_by_sale,
    summarise,
)
from apps.common.tests.purity import django_imports_of

KINSHASA = ZoneInfo("Africa/Kinshasa")
JULY = (date(2026, 7, 1), date(2026, 7, 31))


def at(day, hour=12):
    return datetime(2026, 7, day, hour, tzinfo=dt_timezone.utc)


def sale(id="s1", day=15, status="COMPLETED", total=11_600, vat_total=1_600, **kw):
    row = {
        "id": id,
        "created_at": at(day),
        "status": status,
        "total": total,
        "vat_total": vat_total,
        "reference": f"FA-2026-{id}",
        "customer_name": None,
    }
    row.update(kw)
    return row


def line(
    sale_id="s1",
    article_id="a1",
    quantity=2,
    line_total=11_600,
    discount_share=0,
    vat_amount=1_600,
    unit_cost=3_000,
    **kw,
):
    row = {
        "sale_id": sale_id,
        "article_id": article_id,
        "article_name": "Article",
        "article_sku": "ART-1",
        "quantity": quantity,
        "line_total": line_total,
        "discount_share": discount_share,
        "vat_amount": vat_amount,
        "unit_cost": unit_cost,
    }
    row.update(kw)
    return row


def payment(sale_id="s1", amount=5_000, day=16):
    return {"sale_id": sale_id, "amount": amount, "paid_at": at(day)}


def expense(amount=2_000, category="RENT", day=10):
    return {"category": category, "amount": amount, "spent_at": at(day)}


def purchase(quantity=10, unit_cost=800, day=5):
    return {"quantity": quantity, "unit_cost": unit_cost, "created_at": at(day)}


def facts(**kw):
    base = {"sales": [], "lines": [], "payments": [], "expenses": [], "purchases": []}
    base.update(kw)
    return base


class TestNoDjangoImport:
    def test_the_module_does_not_import_django(self):
        import apps.finance.aggregate as module

        assert django_imports_of(module) == []


class TestLineHelpers:
    def test_line_revenue_is_ht_after_discount(self):
        """Not quantity x unitPrice: that is TTC and ignores the discount
        allocation, so the per-article panel would disagree with the CA card."""
        row = line(line_total=11_600, discount_share=600, vat_amount=1_517)
        assert line_revenue_ht(row) == 11_600 - 600 - 1_517

    def test_line_margin_subtracts_the_cost_snapshot(self):
        row = line(
            quantity=2,
            line_total=10_000,
            discount_share=0,
            vat_amount=1_379,
            unit_cost=3_000,
        )
        assert line_margin(row) == (10_000 - 0 - 1_379) - (2 * 3_000)

    def test_margin_rate_is_an_unrounded_percent(self):
        """Verified bit-identical to JS: (1/3)*100 is 33.33333333333333 in
        both. Rounding here is what would create a difference."""
        assert margin_rate(3, 1) == (1 / 3) * 100
        assert margin_rate(3, 1) == 33.33333333333333

    def test_margin_rate_is_zero_at_zero_revenue(self):
        """Never NaN, never Infinity."""
        assert margin_rate(0, 5) == 0
        assert margin_rate(-10, 5) == 0

    def test_paid_by_sale_folds_once(self):
        totals = paid_by_sale(
            [payment("s1", 100), payment("s2", 50), payment("s1", 25)]
        )
        assert totals == {"s1": 125, "s2": 50}


class TestSummary:
    def test_revenue_is_ht(self):
        result = summarise(
            facts(sales=[sale(total=11_600, vat_total=1_600)]), KINSHASA, *JULY
        )
        assert result["revenue"] == 10_000
        assert result["vat_collected"] == 1_600

    def test_cancelled_sales_are_excluded_from_revenue(self):
        result = summarise(
            facts(sales=[sale(id="s1"), sale(id="s2", status="CANCELLED")]),
            KINSHASA,
            *JULY,
        )
        assert result["revenue"] == 10_000  # only s1

    def test_a_payment_on_a_cancelled_sale_still_counts_as_a_receipt(self):
        """'The cash genuinely moved and there is no refund entity to undo
        it.' Cancellation restores stock, not money."""
        result = summarise(
            facts(
                sales=[sale(id="s1", status="CANCELLED")],
                payments=[payment("s1", 4_000)],
            ),
            KINSHASA,
            *JULY,
        )
        assert result["revenue"] == 0
        assert result["receipts"] == 4_000

    def test_cogs_uses_the_line_cost_snapshot(self):
        result = summarise(
            facts(sales=[sale()], lines=[line(quantity=2, unit_cost=3_000)]),
            KINSHASA,
            *JULY,
        )
        assert result["cogs"] == 6_000
        assert result["gross_margin"] == 10_000 - 6_000

    def test_lines_of_a_cancelled_sale_do_not_contribute_cogs(self):
        result = summarise(
            facts(
                sales=[sale(id="s1", status="CANCELLED")],
                lines=[line(sale_id="s1", quantity=2, unit_cost=3_000)],
            ),
            KINSHASA,
            *JULY,
        )
        assert result["cogs"] == 0

    def test_expenses_and_net_result(self):
        result = summarise(
            facts(sales=[sale()], lines=[line()], expenses=[expense(2_000)]),
            KINSHASA,
            *JULY,
        )
        assert result["expenses"] == 2_000
        assert result["net_result"] == result["gross_margin"] - 2_000

    def test_purchase_disbursements_and_the_missing_cost_count(self):
        result = summarise(
            facts(purchases=[purchase(10, 800), purchase(5, None)]), KINSHASA, *JULY
        )
        assert result["purchase_disbursements"] == 8_000  # the null contributes 0
        assert result["purchases_without_cost"] == 1

    def test_disbursements_and_cash_balance(self):
        result = summarise(
            facts(
                payments=[payment(amount=9_000)],
                expenses=[expense(2_000)],
                purchases=[purchase(10, 800)],
            ),
            KINSHASA,
            *JULY,
        )
        assert result["disbursements"] == 8_000 + 2_000
        assert result["cash_balance"] == 9_000 - 10_000

    def test_out_of_range_rows_are_ignored(self):
        june = {"created_at": datetime(2026, 6, 15, 12, tzinfo=dt_timezone.utc)}
        result = summarise(facts(sales=[sale(**june)]), KINSHASA, *JULY)
        assert result["revenue"] == 0

    def test_range_membership_uses_the_shop_calendar_day(self):
        """23:30 UTC on 30 June is already 1 July in Kinshasa."""
        edge = {"created_at": datetime(2026, 6, 30, 23, 30, tzinfo=dt_timezone.utc)}
        result = summarise(facts(sales=[sale(**edge)]), KINSHASA, *JULY)
        assert result["revenue"] == 10_000


class TestReceivables:
    def test_receivables_ignore_the_range(self):
        """A figure as of now, not for the period — the card says « à ce
        jour »."""
        january = {"created_at": datetime(2026, 1, 15, 12, tzinfo=dt_timezone.utc)}
        result = summarise(
            facts(sales=[sale(total=10_000, **january)]), KINSHASA, *JULY
        )
        assert result["revenue"] == 0
        assert result["receivables"] == 10_000

    def test_payments_reduce_the_balance(self):
        result = summarise(
            facts(sales=[sale(total=10_000)], payments=[payment(amount=4_000)]),
            KINSHASA,
            *JULY,
        )
        assert result["receivables"] == 6_000

    def test_an_overpaid_sale_cannot_lend_its_surplus_to_another(self):
        """Balances are floored at zero before summing."""
        result = summarise(
            facts(
                sales=[sale(id="s1", total=1_000), sale(id="s2", total=5_000)],
                payments=[payment("s1", 3_000)],
            ),
            KINSHASA,
            *JULY,
        )
        # s1's 2 000 overpayment must not offset s2's 5 000 debt.
        assert result["receivables"] == 5_000

    def test_cancelled_sales_are_not_receivable(self):
        result = summarise(
            facts(sales=[sale(status="CANCELLED", total=10_000)]), KINSHASA, *JULY
        )
        assert result["receivables"] == 0


class TestSeries:
    def test_every_bucket_in_the_range_is_present(self):
        result = bucketise(facts(), KINSHASA, date(2026, 7, 1), date(2026, 7, 3))
        assert result["granularity"] == "DAY"
        assert [b["key"] for b in result["buckets"]] == [
            "2026-07-01",
            "2026-07-02",
            "2026-07-03",
        ]

    def test_a_long_range_switches_to_months(self):
        result = bucketise(facts(), KINSHASA, date(2026, 1, 1), date(2026, 12, 31))
        assert result["granularity"] == "MONTH"
        assert len(result["buckets"]) == 12

    def test_revenue_lands_in_its_days_bucket(self):
        result = bucketise(
            facts(sales=[sale(day=2)]), KINSHASA, date(2026, 7, 1), date(2026, 7, 3)
        )
        by_key = {b["key"]: b for b in result["buckets"]}
        assert by_key["2026-07-02"]["revenue"] == 10_000
        assert by_key["2026-07-01"]["revenue"] == 0

    def test_cogs_lands_in_the_bucket_of_its_sale_not_its_line(self):
        """The frontend maps saleId -> bucket first, so revenue and COGS can
        never fall in different buckets."""
        result = bucketise(
            facts(
                sales=[sale(id="s1", day=2)],
                lines=[line(sale_id="s1", quantity=2, unit_cost=3_000)],
            ),
            KINSHASA,
            date(2026, 7, 1),
            date(2026, 7, 3),
        )
        by_key = {b["key"]: b for b in result["buckets"]}
        assert by_key["2026-07-02"]["cogs"] == 6_000
        assert by_key["2026-07-02"]["margin"] == 10_000 - 6_000

    def test_receipts_and_disbursements_bucket_separately(self):
        result = bucketise(
            facts(
                payments=[payment(day=1, amount=5_000)],
                expenses=[expense(day=2, amount=1_000)],
                purchases=[purchase(day=3, quantity=2, unit_cost=500)],
            ),
            KINSHASA,
            date(2026, 7, 1),
            date(2026, 7, 3),
        )
        by_key = {b["key"]: b for b in result["buckets"]}
        assert by_key["2026-07-01"]["receipts"] == 5_000
        assert by_key["2026-07-02"]["disbursements"] == 1_000
        assert by_key["2026-07-03"]["disbursements"] == 1_000

    def test_cumulative_cash_restarts_at_zero_in_the_first_bucket(self):
        """It answers 'what did this period do to my cash', not 'what is in
        the till'."""
        result = bucketise(
            facts(
                payments=[
                    payment(day=1, amount=5_000),
                    payment(day=3, amount=2_000),
                ],
                expenses=[expense(day=2, amount=1_000)],
            ),
            KINSHASA,
            date(2026, 7, 1),
            date(2026, 7, 3),
        )
        assert [b["cumulative_cash"] for b in result["buckets"]] == [
            5_000,
            4_000,
            6_000,
        ]

    def test_a_cancelled_sale_contributes_no_revenue_to_any_bucket(self):
        result = bucketise(
            facts(sales=[sale(day=2, status="CANCELLED")]),
            KINSHASA,
            date(2026, 7, 1),
            date(2026, 7, 3),
        )
        assert all(b["revenue"] == 0 for b in result["buckets"])


class TestBreakdown:
    def test_expense_rows_are_largest_first_with_shares(self):
        result = build_breakdown(
            facts(expenses=[expense(3_000, "RENT"), expense(1_000, "TRANSPORT")]),
            KINSHASA,
            *JULY,
        )
        rows = result["expenses"]
        assert [r["category"] for r in rows] == ["RENT", "TRANSPORT"]
        assert rows[0]["share"] == 75.0
        assert rows[1]["share"] == 25.0

    def test_shares_are_unrounded(self):
        result = build_breakdown(
            facts(
                expenses=[
                    expense(1_000, "RENT"),
                    expense(1_000, "TAX"),
                    expense(1_000, "SALARY"),
                ]
            ),
            KINSHASA,
            *JULY,
        )
        assert result["expenses"][0]["share"] == (1 / 3) * 100

    def test_categories_are_folded(self):
        result = build_breakdown(
            facts(expenses=[expense(1_000, "RENT"), expense(2_000, "RENT")]),
            KINSHASA,
            *JULY,
        )
        assert len(result["expenses"]) == 1
        assert result["expenses"][0]["amount"] == 3_000

    def test_a_zero_total_yields_zero_shares_not_a_division_error(self):
        result = build_breakdown(facts(expenses=[expense(0, "RENT")]), KINSHASA, *JULY)
        assert result["expenses"][0]["share"] == 0

    def test_top_articles_are_capped_at_five(self):
        assert TOP_ARTICLE_COUNT == 5
        rows = [
            line(
                article_id=f"a{i}",
                quantity=1,
                line_total=1_000 * (i + 1),
                vat_amount=0,
                unit_cost=0,
            )
            for i in range(8)
        ]
        result = build_breakdown(facts(sales=[sale()], lines=rows), KINSHASA, *JULY)
        assert len(result["top_articles"]) == 5

    def test_top_articles_are_ranked_by_margin(self):
        rows = [
            line(
                article_id="low",
                line_total=2_000,
                vat_amount=0,
                quantity=1,
                unit_cost=1_900,
            ),
            line(
                article_id="high",
                line_total=2_000,
                vat_amount=0,
                quantity=1,
                unit_cost=100,
            ),
        ]
        result = build_breakdown(facts(sales=[sale()], lines=rows), KINSHASA, *JULY)
        assert [r["article_id"] for r in result["top_articles"]] == ["high", "low"]

    def test_the_same_article_across_lines_is_folded(self):
        rows = [
            line(
                article_id="a1", quantity=1, line_total=1_000, vat_amount=0, unit_cost=0
            ),
            line(
                article_id="a1", quantity=2, line_total=2_000, vat_amount=0, unit_cost=0
            ),
        ]
        result = build_breakdown(facts(sales=[sale()], lines=rows), KINSHASA, *JULY)
        assert len(result["top_articles"]) == 1
        assert result["top_articles"][0]["quantity"] == 3
        assert result["top_articles"][0]["revenue"] == 3_000

    def test_unpaid_sales_ignore_the_range(self):
        january = {"created_at": datetime(2026, 1, 15, 12, tzinfo=dt_timezone.utc)}
        result = build_breakdown(
            facts(sales=[sale(total=10_000, **january)]), KINSHASA, *JULY
        )
        assert len(result["unpaid_sales"]) == 1

    def test_a_fully_paid_sale_is_not_listed(self):
        result = build_breakdown(
            facts(sales=[sale(total=10_000)], payments=[payment(amount=10_000)]),
            KINSHASA,
            *JULY,
        )
        assert result["unpaid_sales"] == []

    def test_unpaid_sales_are_largest_balance_first(self):
        result = build_breakdown(
            facts(sales=[sale(id="small", total=1_000), sale(id="big", total=9_000)]),
            KINSHASA,
            *JULY,
        )
        assert [r["id"] for r in result["unpaid_sales"]] == ["big", "small"]

    def test_cancelled_sales_are_not_unpaid(self):
        result = build_breakdown(
            facts(sales=[sale(status="CANCELLED", total=10_000)]), KINSHASA, *JULY
        )
        assert result["unpaid_sales"] == []


NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="node is not on PATH")
class TestAgainstTheFrontendImplementation:
    """Randomised facts through the frontend's own aggregate.ts, diffed.

    The port is long enough that hand-written cases cannot cover the
    interactions between range filtering, cancellation and the two unbounded
    folds. This can.
    """

    JS = """
    const inRange = (iso, r) => { const d = iso.slice(0, 10); return d >= r.from && d <= r.to; };
    const sumBy = (xs, f) => xs.reduce((t, x) => t + f(x), 0);
    const paidBySale = (ps) => { const m = new Map();
      for (const p of ps) m.set(p.saleId, (m.get(p.saleId) ?? 0) + p.amount); return m; };
    const completed = (f, r) => f.sales.filter(s => s.status === "COMPLETED" && inRange(s.createdAt, r));
    const linesOf = (f, sales) => { const ids = new Set(sales.map(s => s.id));
      return f.lines.filter(l => ids.has(l.saleId)); };

    function summarise(f, r) {
      const sales = completed(f, r), lines = linesOf(f, sales);
      const revenue = sumBy(sales, s => s.total - s.vatTotal);
      const cogs = sumBy(lines, l => l.quantity * l.unitCost);
      const grossMargin = revenue - cogs;
      const expenses = sumBy(f.expenses.filter(e => inRange(e.spentAt, r)), e => e.amount);
      const receipts = sumBy(f.payments.filter(p => inRange(p.paidAt, r)), p => p.amount);
      const purchases = f.purchases.filter(p => inRange(p.createdAt, r));
      const purchaseDisbursements = sumBy(purchases, p => p.quantity * (p.unitCost ?? 0));
      const paid = paidBySale(f.payments);
      const receivables = f.sales.filter(s => s.status === "COMPLETED")
        .reduce((t, s) => t + Math.max(s.total - (paid.get(s.id) ?? 0), 0), 0);
      const disbursements = purchaseDisbursements + expenses;
      return { revenue, cogs, grossMargin,
        marginRate: revenue <= 0 ? 0 : (grossMargin / revenue) * 100,
        expenses, netResult: grossMargin - expenses,
        vatCollected: sumBy(sales, s => s.vatTotal), receipts,
        purchaseDisbursements, disbursements, cashBalance: receipts - disbursements,
        receivables, purchasesWithoutCost: purchases.filter(p => p.unitCost === null).length };
    }

    const [factsIn, range] = JSON.parse(process.argv[1]);
    console.log(JSON.stringify(summarise(factsIn, range)));
    """

    def test_the_summary_matches_on_randomised_facts(self):
        random.seed(20260808)

        for _ in range(60):
            js_facts = {
                "sales": [],
                "lines": [],
                "payments": [],
                "expenses": [],
                "purchases": [],
            }
            py_facts = facts()

            for index in range(random.randint(0, 6)):
                sale_id = f"s{index}"
                day = random.randint(1, 28)
                month = random.choice([6, 7, 8])
                status = random.choice(["COMPLETED", "COMPLETED", "CANCELLED"])
                total = random.randint(0, 50_000)
                vat = random.randint(0, total) if total else 0
                moment = datetime(2026, month, day, 12, tzinfo=dt_timezone.utc)
                iso = moment.isoformat().replace("+00:00", "Z")

                js_facts["sales"].append(
                    {
                        "id": sale_id,
                        "createdAt": iso,
                        "status": status,
                        "total": total,
                        "vatTotal": vat,
                    }
                )
                py_facts["sales"].append(
                    {
                        "id": sale_id,
                        "created_at": moment,
                        "status": status,
                        "total": total,
                        "vat_total": vat,
                        "reference": "",
                        "customer_name": None,
                    }
                )

                for _line in range(random.randint(0, 3)):
                    quantity = random.randint(1, 5)
                    unit_cost = random.randint(0, 2_000)
                    js_facts["lines"].append(
                        {
                            "saleId": sale_id,
                            "articleId": "a",
                            "articleName": "A",
                            "articleSku": "A",
                            "quantity": quantity,
                            "lineTotal": 0,
                            "discountShare": 0,
                            "vatAmount": 0,
                            "unitCost": unit_cost,
                        }
                    )
                    py_facts["lines"].append(
                        {
                            "sale_id": sale_id,
                            "article_id": "a",
                            "article_name": "A",
                            "article_sku": "A",
                            "quantity": quantity,
                            "line_total": 0,
                            "discount_share": 0,
                            "vat_amount": 0,
                            "unit_cost": unit_cost,
                        }
                    )

                if random.random() < 0.7:
                    amount = random.randint(0, total + 5_000)
                    js_facts["payments"].append(
                        {"saleId": sale_id, "paidAt": iso, "amount": amount}
                    )
                    py_facts["payments"].append(
                        {"sale_id": sale_id, "paid_at": moment, "amount": amount}
                    )

            for _ in range(random.randint(0, 4)):
                moment = datetime(
                    2026,
                    random.choice([6, 7, 8]),
                    random.randint(1, 28),
                    12,
                    tzinfo=dt_timezone.utc,
                )
                iso = moment.isoformat().replace("+00:00", "Z")
                amount = random.randint(0, 20_000)
                category = random.choice(["RENT", "TAX", "OTHER"])
                js_facts["expenses"].append(
                    {"category": category, "amount": amount, "spentAt": iso}
                )
                py_facts["expenses"].append(
                    {"category": category, "amount": amount, "spent_at": moment}
                )

            for _ in range(random.randint(0, 4)):
                moment = datetime(
                    2026,
                    random.choice([6, 7, 8]),
                    random.randint(1, 28),
                    12,
                    tzinfo=dt_timezone.utc,
                )
                iso = moment.isoformat().replace("+00:00", "Z")
                quantity = random.randint(1, 20)
                unit_cost = random.choice([None, random.randint(0, 3_000)])
                js_facts["purchases"].append(
                    {"quantity": quantity, "unitCost": unit_cost, "createdAt": iso}
                )
                py_facts["purchases"].append(
                    {"quantity": quantity, "unit_cost": unit_cost, "created_at": moment}
                )

            payload = json.dumps([js_facts, {"from": "2026-07-01", "to": "2026-07-31"}])
            result = subprocess.run(
                [NODE, "-e", self.JS, payload],
                capture_output=True,
                text=True,
                check=True,
            )
            want = json.loads(result.stdout)

            # UTC noon and Kinshasa share a calendar day, so the JS string
            # comparison and the Python tz-aware one agree by construction.
            got = summarise(py_facts, dt_timezone.utc, *JULY)

            for js_key, py_key in [
                ("revenue", "revenue"),
                ("cogs", "cogs"),
                ("grossMargin", "gross_margin"),
                ("marginRate", "margin_rate"),
                ("expenses", "expenses"),
                ("netResult", "net_result"),
                ("vatCollected", "vat_collected"),
                ("receipts", "receipts"),
                ("purchaseDisbursements", "purchase_disbursements"),
                ("disbursements", "disbursements"),
                ("cashBalance", "cash_balance"),
                ("receivables", "receivables"),
                ("purchasesWithoutCost", "purchases_without_cost"),
            ]:
                assert got[py_key] == want[js_key], f"{py_key} differs"
