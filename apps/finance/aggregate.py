"""Finance aggregation, ported from features/finance/lib/aggregate.ts.

Imports nothing from Django. The facts arrive as plain dicts from
`apps.finance.facts`, which is the only file here that touches the ORM.

Money is integer cents throughout. The two percentages — `margin_rate` and a
breakdown row's `share` — are **unrounded floats**, exactly as the frontend
computes them. Python and JavaScript agree bit-for-bit on an unrounded IEEE-754
division; rounding either side is what would make them differ.
"""

from datetime import date, tzinfo

from apps.finance.period import (
    bucket_key,
    enumerate_buckets,
    in_range,
    resolve_granularity,
)

TOP_ARTICLE_COUNT = 5


def line_revenue_ht(line: dict) -> int:
    """A line's share of the sale's HT revenue.

    Not `quantity × unit_price`: that is TTC and ignores the sale's discount
    allocation, so the per-article panel would disagree with the revenue card.
    These roll up exactly — Σ line_total = subtotal, Σ discount_share =
    discount, Σ vat_amount = vat_total.
    """
    return line["line_total"] - line["discount_share"] - line["vat_amount"]


def line_margin(line: dict) -> int:
    return line_revenue_ht(line) - line["quantity"] * line["unit_cost"]


def margin_rate(revenue: int, margin: int) -> float:
    """Percent. Zero revenue yields 0, never NaN or a division error.

    Deliberately unrounded — see the module docstring.
    """
    if revenue <= 0:
        return 0
    return (margin / revenue) * 100


def paid_by_sale(payments: list[dict]) -> dict:
    """Total paid per sale, folded once.

    Three callers depend on this agreeing with itself: receivables, the
    unpaid-sales panel, and sub-project 6's « réglé » column.
    """
    totals: dict = {}
    for row in payments:
        totals[row["sale_id"]] = totals.get(row["sale_id"], 0) + row["amount"]
    return totals


def _completed_in_range(facts, tz, start, end) -> list[dict]:
    return [
        row
        for row in facts["sales"]
        if row["status"] == "COMPLETED" and in_range(row["created_at"], tz, start, end)
    ]


def _lines_of(facts, sales) -> list[dict]:
    sale_ids = {row["id"] for row in sales}
    return [row for row in facts["lines"] if row["sale_id"] in sale_ids]


def _receivables(facts) -> int:
    """Outstanding across every completed sale, whenever it happened.

    A figure as of now, not for the period, which is why it takes no range.
    Each balance is floored at zero first: a sale paid past its total must not
    lend its overpayment to another's balance.
    """
    paid = paid_by_sale(facts["payments"])
    return sum(
        max(row["total"] - paid.get(row["id"], 0), 0)
        for row in facts["sales"]
        if row["status"] == "COMPLETED"
    )


def summarise(facts: dict, tz: tzinfo, start: date, end: date) -> dict:
    sales = _completed_in_range(facts, tz, start, end)
    lines = _lines_of(facts, sales)

    revenue = sum(row["total"] - row["vat_total"] for row in sales)
    vat_collected = sum(row["vat_total"] for row in sales)
    cogs = sum(row["quantity"] * row["unit_cost"] for row in lines)
    gross_margin = revenue - cogs

    expenses = sum(
        row["amount"]
        for row in facts["expenses"]
        if in_range(row["spent_at"], tz, start, end)
    )

    # Every payment in the window, including those on sales later cancelled:
    # the cash genuinely moved and there is no refund entity to undo it.
    receipts = sum(
        row["amount"]
        for row in facts["payments"]
        if in_range(row["paid_at"], tz, start, end)
    )

    purchases = [
        row for row in facts["purchases"] if in_range(row["created_at"], tz, start, end)
    ]
    purchase_disbursements = sum(
        row["quantity"] * (row["unit_cost"] or 0) for row in purchases
    )
    purchases_without_cost = sum(1 for row in purchases if row["unit_cost"] is None)

    disbursements = purchase_disbursements + expenses

    return {
        "revenue": revenue,
        "cogs": cogs,
        "gross_margin": gross_margin,
        "margin_rate": margin_rate(revenue, gross_margin),
        "expenses": expenses,
        "net_result": gross_margin - expenses,
        "vat_collected": vat_collected,
        "receipts": receipts,
        "purchase_disbursements": purchase_disbursements,
        "disbursements": disbursements,
        "cash_balance": receipts - disbursements,
        "receivables": _receivables(facts),
        "purchases_without_cost": purchases_without_cost,
    }


def bucketise(facts: dict, tz: tzinfo, start: date, end: date) -> dict:
    granularity = resolve_granularity(start, end)

    buckets: list[dict] = []
    by_key: dict = {}
    for slot in enumerate_buckets(start, end, granularity):
        bucket = {
            "key": slot.key,
            "label": slot.label,
            "revenue": 0,
            "cogs": 0,
            "margin": 0,
            "receipts": 0,
            "disbursements": 0,
            "cumulative_cash": 0,
        }
        buckets.append(bucket)
        by_key[slot.key] = bucket

    sales = _completed_in_range(facts, tz, start, end)

    # A sale's bucket is resolved once and its lines follow it, so revenue and
    # COGS can never fall in different buckets.
    bucket_by_sale: dict = {}
    for row in sales:
        bucket = by_key.get(bucket_key(row["created_at"], tz, granularity))
        bucket_by_sale[row["id"]] = bucket
        if bucket:
            bucket["revenue"] += row["total"] - row["vat_total"]

    for row in _lines_of(facts, sales):
        bucket = bucket_by_sale.get(row["sale_id"])
        if bucket:
            bucket["cogs"] += row["quantity"] * row["unit_cost"]

    for row in facts["payments"]:
        if not in_range(row["paid_at"], tz, start, end):
            continue
        bucket = by_key.get(bucket_key(row["paid_at"], tz, granularity))
        if bucket:
            bucket["receipts"] += row["amount"]

    for row in facts["expenses"]:
        if not in_range(row["spent_at"], tz, start, end):
            continue
        bucket = by_key.get(bucket_key(row["spent_at"], tz, granularity))
        if bucket:
            bucket["disbursements"] += row["amount"]

    for row in facts["purchases"]:
        if not in_range(row["created_at"], tz, start, end):
            continue
        bucket = by_key.get(bucket_key(row["created_at"], tz, granularity))
        if bucket:
            bucket["disbursements"] += row["quantity"] * (row["unit_cost"] or 0)

    # Margin and the running balance are derived once the buckets are filled.
    # The cumulative line starts at zero at the period's first bucket: it
    # answers "what did this period do to my cash", not "what is in the till".
    running = 0
    for bucket in buckets:
        bucket["margin"] = bucket["revenue"] - bucket["cogs"]
        running += bucket["receipts"] - bucket["disbursements"]
        bucket["cumulative_cash"] = running

    return {"granularity": granularity, "buckets": buckets}


def build_expense_breakdown(facts, tz, start, end) -> list[dict]:
    totals: dict = {}
    for row in facts["expenses"]:
        if not in_range(row["spent_at"], tz, start, end):
            continue
        totals[row["category"]] = totals.get(row["category"], 0) + row["amount"]

    total = sum(totals.values())

    rows = [
        {
            "category": category,
            "amount": amount,
            "share": (amount / total) * 100 if total > 0 else 0,
        }
        for category, amount in totals.items()
    ]
    rows.sort(key=lambda row: -row["amount"])
    return rows


def build_top_articles(facts, tz, start, end) -> list[dict]:
    sales = _completed_in_range(facts, tz, start, end)
    by_article: dict = {}

    for row in _lines_of(facts, sales):
        existing = by_article.get(row["article_id"])
        if existing:
            existing["quantity"] += row["quantity"]
            existing["revenue"] += line_revenue_ht(row)
            existing["margin"] += line_margin(row)
            continue
        by_article[row["article_id"]] = {
            "article_id": row["article_id"],
            "article_name": row["article_name"],
            "article_sku": row["article_sku"],
            "quantity": row["quantity"],
            "revenue": line_revenue_ht(row),
            "margin": line_margin(row),
        }

    rows = sorted(by_article.values(), key=lambda row: -row["margin"])
    return rows[:TOP_ARTICLE_COUNT]


def build_unpaid_sales(facts) -> list[dict]:
    """Not range-scoped, for the same reason as receivables."""
    paid = paid_by_sale(facts["payments"])

    rows = [
        {
            "id": row["id"],
            "reference": row.get("reference") or "",
            "customer_name": row.get("customer_name"),
            "created_at": row["created_at"],
            "total": row["total"],
            "balance": row["total"] - paid.get(row["id"], 0),
        }
        for row in facts["sales"]
        if row["status"] == "COMPLETED"
    ]
    rows = [row for row in rows if row["balance"] > 0]
    rows.sort(key=lambda row: -row["balance"])
    return rows


def build_breakdown(facts: dict, tz: tzinfo, start: date, end: date) -> dict:
    return {
        "expenses": build_expense_breakdown(facts, tz, start, end),
        "top_articles": build_top_articles(facts, tz, start, end),
        "unpaid_sales": build_unpaid_sales(facts),
    }
