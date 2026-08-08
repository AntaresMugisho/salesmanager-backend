"""Randomised facts through a transcription of the frontend builders, diffed.

The JS below is a **transcription** of `features/reports/lib/*.ts`, not an
import of it — running the real modules would need a TypeScript toolchain in
the test path. So this catches Python/JavaScript semantic divergence (integer
division, sort stability, rounding, date handling); it does not catch a
transcription that is faithfully wrong in both languages. Read the frontend
source alongside it when changing either.

Facts are stamped at 12:00 UTC and folded with `dt_timezone.utc`, so the JS
string comparison on `createdAt.slice(0, 10)` and the Python tz-aware one agree
by construction. Changing the hour breaks that and the failures are confusing.
"""

import json
import random
import shutil
import subprocess
from datetime import datetime, timezone as dt_timezone

import pytest

from apps.reports.profitability import build_profitability_report
from apps.reports.sales import build_sales_report
from apps.reports.tests.support import GENERATED_AT, JULY

NODE = shutil.which("node")

RANGE = {"from": "2026-07-01", "to": "2026-07-31"}
CATALOGUE = {
    f"a{i}": {
        "article_id": f"a{i}",
        "sku": f"ART-{i}",
        "name": f"Article {i}",
        "unit": "PIECE",
        "purchase_price": 500,
        "category_id": f"c{i % 2}",
        "category_name": f"Catégorie {i % 2}",
    }
    for i in range(4)
}


def randomised_facts(seed_index):
    """One randomised fact set, in both the JS and the Python shape."""
    js = {"sales": [], "lines": [], "payments": [], "expenses": [], "purchases": []}
    py = {"sales": [], "lines": [], "payments": [], "expenses": [], "purchases": []}

    for index in range(random.randint(0, 6)):
        sale_id = f"s{seed_index}_{index}"
        month = random.choice([6, 7, 8])
        day = random.randint(1, 28)
        status = random.choice(["COMPLETED", "COMPLETED", "CANCELLED"])
        total = random.randint(0, 50_000)
        vat = random.randint(0, total) if total else 0
        discount = random.randint(0, 2_000)
        customer = random.choice([None, "cust1", "cust2"])
        moment = datetime(2026, month, day, 12, tzinfo=dt_timezone.utc)
        iso = moment.isoformat().replace("+00:00", "Z")

        js["sales"].append(
            {
                "id": sale_id,
                "createdAt": iso,
                "status": status,
                "total": total,
                "vatTotal": vat,
                "discount": discount,
                "reference": f"FA-{sale_id}",
                "customerId": customer,
                "customerName": None if customer is None else f"Client {customer}",
            }
        )
        py["sales"].append(
            {
                "id": sale_id,
                "created_at": moment,
                "status": status,
                "total": total,
                "vat_total": vat,
                "discount": discount,
                "reference": f"FA-{sale_id}",
                "customer_id": customer,
                "customer_name": None if customer is None else f"Client {customer}",
            }
        )

        for _line_index in range(random.randint(0, 3)):
            article_id = f"a{random.randint(0, 3)}"
            quantity = random.randint(1, 5)

            if random.random() < 0.25:
                # A line whose margin is exactly zero. Purely random values
                # essentially never produce one, which left the `margin <= 0`
                # boundary in lowMargin untested — a mutation to `< 0` passed
                # this comparison until these lines were added.
                unit_cost = random.randint(0, 2_000)
                discount_share = random.randint(0, 500)
                vat_amount = random.randint(0, 2_000)
                line_total = quantity * unit_cost + discount_share + vat_amount
            else:
                line_total = random.randint(0, 20_000)
                discount_share = random.randint(0, min(line_total, 1_000))
                vat_amount = random.randint(0, max(line_total - discount_share, 0))
                unit_cost = random.randint(0, 4_000)

            js["lines"].append(
                {
                    "saleId": sale_id,
                    "articleId": article_id,
                    "articleName": f"Article {article_id}",
                    "articleSku": f"SKU-{article_id}",
                    "quantity": quantity,
                    "lineTotal": line_total,
                    "discountShare": discount_share,
                    "vatAmount": vat_amount,
                    "unitCost": unit_cost,
                    "vatRate": 16,
                }
            )
            py["lines"].append(
                {
                    "sale_id": sale_id,
                    "article_id": article_id,
                    "article_name": f"Article {article_id}",
                    "article_sku": f"SKU-{article_id}",
                    "quantity": quantity,
                    "line_total": line_total,
                    "discount_share": discount_share,
                    "vat_amount": vat_amount,
                    "unit_cost": unit_cost,
                    "vat_rate": 16,
                }
            )

        if random.random() < 0.6:
            pay_day = random.randint(1, 28)
            pay_moment = datetime(2026, 7, pay_day, 12, tzinfo=dt_timezone.utc)
            amount = random.randint(0, 30_000)
            js["payments"].append(
                {
                    "saleId": sale_id,
                    "amount": amount,
                    "paidAt": pay_moment.isoformat().replace("+00:00", "Z"),
                }
            )
            py["payments"].append(
                {"sale_id": sale_id, "amount": amount, "paid_at": pay_moment}
            )

    return js, py


def run(js_source, payload):
    result = subprocess.run(
        [NODE, "-e", js_source, json.dumps(payload)],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


PROFITABILITY_JS = """
const inRange = (iso, r) => { const d = iso.slice(0, 10); return d >= r.from && d <= r.to; };
const lineRevenueHT = (l) => l.lineTotal - l.discountShare - l.vatAmount;
const lineMargin = (l) => lineRevenueHT(l) - l.quantity * l.unitCost;
const marginRate = (rev, m) => (rev <= 0 ? 0 : (m / rev) * 100);

const [facts, catalogue, range] = JSON.parse(process.argv[1]);

const completed = new Set(
  facts.sales
    .filter((s) => s.status === "COMPLETED" && inRange(s.createdAt, range))
    .map((s) => s.id)
);

const blank = (id, name, sku) => ({
  id, name, sku, quantity: 0, revenue: 0, cogs: 0, margin: 0, marginRate: 0,
});
const accumulate = (row, l) => {
  row.quantity += l.quantity;
  row.revenue += lineRevenueHT(l);
  row.cogs += l.quantity * l.unitCost;
  row.margin += lineMargin(l);
};

const byArticle = new Map(), byCategory = new Map();
for (const l of facts.lines) {
  if (!completed.has(l.saleId)) continue;
  const a = byArticle.get(l.articleId) ?? blank(l.articleId, l.articleName, l.articleSku);
  accumulate(a, l); byArticle.set(l.articleId, a);
  const entry = catalogue[l.articleId];
  const c = byCategory.get(entry.categoryId) ?? blank(entry.categoryId, entry.categoryName, null);
  accumulate(c, l); byCategory.set(entry.categoryId, c);
}

// Sorted with the same explicit id tie-break the Python uses, so the
// comparison tests the arithmetic rather than two sort stabilities.
const finish = (rows) => rows
  .map((r) => ({ ...r, marginRate: marginRate(r.revenue, r.margin) }))
  .sort((a, b) => (b.margin - a.margin) || String(a.id).localeCompare(String(b.id)));

const articles = finish([...byArticle.values()]);
const totals = articles.reduce(
  (t, r) => ({
    quantity: t.quantity + r.quantity, revenue: t.revenue + r.revenue,
    cogs: t.cogs + r.cogs, margin: t.margin + r.margin, marginRate: 0,
  }),
  { quantity: 0, revenue: 0, cogs: 0, margin: 0, marginRate: 0 }
);
totals.marginRate = marginRate(totals.revenue, totals.margin);

process.stdout.write(JSON.stringify({
  articles,
  categories: finish([...byCategory.values()]),
  lowMargin: articles.filter((r) => r.margin <= 0)
    .sort((a, b) => (a.margin - b.margin) || String(a.id).localeCompare(String(b.id))),
  totals,
}));
"""


@pytest.mark.skipif(NODE is None, reason="node is not on PATH")
class TestProfitabilityAgainstTheFrontend:
    def test_it_matches_on_randomised_facts(self):
        random.seed(20260808)

        for index in range(40):
            js_facts, py_facts = randomised_facts(index)
            want = run(PROFITABILITY_JS, [js_facts, CATALOGUE, RANGE])
            got = build_profitability_report(
                py_facts, CATALOGUE, dt_timezone.utc, *JULY, GENERATED_AT
            )

            assert [r["id"] for r in got["articles"]] == [
                r["id"] for r in want["articles"]
            ], f"article order differs at iteration {index}"
            assert [r["id"] for r in got["low_margin"]] == [
                r["id"] for r in want["lowMargin"]
            ], f"lowMargin order differs at iteration {index}"

            for js_key, py_key in [
                ("quantity", "quantity"),
                ("revenue", "revenue"),
                ("cogs", "cogs"),
                ("margin", "margin"),
                ("marginRate", "margin_rate"),
            ]:
                assert got["totals"][py_key] == want["totals"][js_key], (
                    f"totals.{py_key} differs at iteration {index}"
                )
                for mine, theirs in zip(got["articles"], want["articles"]):
                    assert mine[py_key] == theirs[js_key], (
                        f"articles[{mine['id']}].{py_key} differs at {index}"
                    )


SALES_JS = """
const inRange = (iso, r) => { const d = iso.slice(0, 10); return d >= r.from && d <= r.to; };
const sumBy = (xs, f) => xs.reduce((t, x) => t + f(x), 0);
const paidBySale = (ps) => { const m = new Map();
  for (const p of ps) m.set(p.saleId, (m.get(p.saleId) ?? 0) + p.amount); return m; };
const computeBalance = (total, paid, status) =>
  status === "CANCELLED" ? 0 : Math.max(total - paid, 0);

const WALK_IN = "Client de passage";
const [facts, range] = JSON.parse(process.argv[1]);

const paid = paidBySale(facts.payments);
const inPeriod = facts.sales.filter((s) => inRange(s.createdAt, range));
const completed = inPeriod.filter((s) => s.status === "COMPLETED");

const invoices = inPeriod
  .map((s) => ({
    id: s.id,
    customerName: s.customerName ?? WALK_IN,
    total: s.total,
    paid: paid.get(s.id) ?? 0,
    balance: computeBalance(s.total, paid.get(s.id) ?? 0, s.status),
  }))
  .sort((a, b) => String(a.id).localeCompare(String(b.id)));

const byCustomer = new Map();
for (const s of completed) {
  const key = s.customerId ?? "__walk_in__";
  const p = paid.get(s.id) ?? 0;
  const row = byCustomer.get(key) ?? {
    customerId: s.customerId ?? null,
    customerName: s.customerName ?? WALK_IN,
    invoiceCount: 0, total: 0, paid: 0, balance: 0,
  };
  row.invoiceCount += 1; row.total += s.total; row.paid += p;
  row.balance += Math.max(s.total - p, 0);
  byCustomer.set(key, row);
}

process.stdout.write(JSON.stringify({
  totals: {
    invoiceCount: completed.length,
    cancelledCount: inPeriod.length - completed.length,
    totalTtc: sumBy(completed, (s) => s.total),
    discounts: sumBy(completed, (s) => s.discount),
  },
  invoices,
  customers: [...byCustomer.values()]
    .sort((a, b) => (b.total - a.total) || String(a.customerId ?? "").localeCompare(String(b.customerId ?? ""))),
}));
"""


@pytest.mark.skipif(NODE is None, reason="node is not on PATH")
class TestSalesAgainstTheFrontend:
    def test_it_matches_on_randomised_facts(self):
        random.seed(20260809)

        for index in range(40):
            js_facts, py_facts = randomised_facts(index)
            want = run(SALES_JS, [js_facts, RANGE])
            got = build_sales_report(py_facts, dt_timezone.utc, *JULY, GENERATED_AT)

            for js_key, py_key in [
                ("invoiceCount", "invoice_count"),
                ("cancelledCount", "cancelled_count"),
                ("totalTtc", "total_ttc"),
                ("discounts", "discounts"),
            ]:
                assert got["totals"][py_key] == want["totals"][js_key], (
                    f"totals.{py_key} differs at iteration {index}"
                )

            # Both sides sorted by id so the comparison is of content, not of
            # two tie-break implementations.
            mine = sorted(got["invoices"], key=lambda r: str(r["id"]))
            for row, theirs in zip(mine, want["invoices"]):
                assert row["paid"] == theirs["paid"]
                assert row["balance"] == theirs["balance"]
                assert row["customer_name"] == theirs["customerName"]

            assert [r["customer_id"] for r in got["customers"]] == [
                r["customerId"] for r in want["customers"]
            ], f"customer order differs at iteration {index}"
            for row, theirs in zip(got["customers"], want["customers"]):
                assert row["invoice_count"] == theirs["invoiceCount"]
                assert row["total"] == theirs["total"]
                assert row["balance"] == theirs["balance"]
