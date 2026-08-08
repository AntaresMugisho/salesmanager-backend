"""Margin by article and by category.

Every figure starts from `line_revenue_ht` and `line_margin`, the same per-line
functions /finances uses, so these rows roll up to the compte de résultat's
totals by construction rather than by coincidence.

The article's name and SKU come from the sale line's snapshot, never from the
catalogue: a renamed or repriced article must not rewrite what a past period
says was sold. The catalogue is consulted for one thing only — which category
the article belongs to.
"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from apps.finance.aggregate import line_margin, line_revenue_ht, margin_rate
from apps.finance.period import in_range
from apps.reports.meta import report_meta

COMPLETED = "COMPLETED"


def _blank_row(row_id, name: str, sku: str | None) -> dict:
    return {
        "id": row_id,
        "name": name,
        "sku": sku,
        "quantity": 0,
        "revenue": 0,
        "cogs": 0,
        "margin": 0,
        "margin_rate": 0,
    }


def _accumulate(row: dict, line: dict) -> None:
    row["quantity"] += line["quantity"]
    row["revenue"] += line_revenue_ht(line)
    row["cogs"] += line["quantity"] * line["unit_cost"]
    row["margin"] += line_margin(line)


def _finish(rows: list[dict]) -> list[dict]:
    for row in rows:
        row["margin_rate"] = margin_rate(row["revenue"], row["margin"])
    # Explicit id tie-break so two rows with equal margin cannot swap between
    # requests.
    return sorted(rows, key=lambda row: (-row["margin"], str(row["id"])))


def build_profitability_report(
    facts: dict,
    catalogue: dict,
    tz: ZoneInfo,
    start: date,
    end: date,
    generated_at: datetime,
) -> dict:
    completed_ids = {
        sale["id"]
        for sale in facts["sales"]
        if sale["status"] == COMPLETED and in_range(sale["created_at"], tz, start, end)
    }

    by_article: dict = {}
    by_category: dict = {}

    for line in facts["lines"]:
        if line["sale_id"] not in completed_ids:
            continue

        article_row = by_article.get(line["article_id"])
        if article_row is None:
            article_row = _blank_row(
                line["article_id"], line["article_name"], line["article_sku"]
            )
            by_article[line["article_id"]] = article_row
        _accumulate(article_row, line)

        # Every sold article is present: SaleLine.article is PROTECT, so the
        # database refuses to delete one that has been sold. No fallback.
        entry = catalogue[line["article_id"]]
        category_row = by_category.get(entry["category_id"])
        if category_row is None:
            category_row = _blank_row(entry["category_id"], entry["category_name"], None)
            by_category[entry["category_id"]] = category_row
        _accumulate(category_row, line)

    articles = _finish(list(by_article.values()))
    categories = _finish(list(by_category.values()))

    totals = {
        "quantity": sum(row["quantity"] for row in articles),
        "revenue": sum(row["revenue"] for row in articles),
        "cogs": sum(row["cogs"] for row in articles),
        "margin": sum(row["margin"] for row in articles),
    }
    totals["margin_rate"] = margin_rate(totals["revenue"], totals["margin"])

    return {
        "meta": report_meta(start, end, generated_at),
        "categories": categories,
        "articles": articles,
        # Worst first: this is the actionable half of the document, so the
        # article losing the most money is the first thing read.
        "low_margin": sorted(
            (row for row in articles if row["margin"] <= 0),
            key=lambda row: (row["margin"], str(row["id"])),
        ),
        "totals": totals,
    }
