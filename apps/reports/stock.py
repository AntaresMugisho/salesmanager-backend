"""The rapport de stock et mouvements.

Two halves that do not share a date: `categories` and `stock_totals` describe
stock as of `meta.generated_at`, everything below describes `meta.range`. The
document states this in words, and the inventory half is deliberately not
range-filtered.
"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from apps.common.collation import collation_key
from apps.finance.period import in_range
from apps.reports.meta import report_meta
from apps.stock.status import derive_stock_status

#: Purchases with no transaction, or whose transaction names no supplier.
NO_SUPPLIER_LABEL = "Fournisseur non renseigné"
NO_SUPPLIER_KEY = "__no_supplier__"

#: Fixed order so the summary table reads the same way every time.
TYPE_ORDER = ["IN", "OUT", "ADJUSTMENT"]
REASON_ORDER = [
    "PURCHASE",
    "SALE",
    "RETURN",
    "DAMAGE",
    "LOSS",
    "COUNT_CORRECTION",
    "OTHER",
]


def _inventory(rows: dict) -> tuple[list[dict], dict]:
    catalogue = rows["catalogue"]
    groups: dict = {}

    for level in rows["levels"]:
        # Every level's article exists: StockLevel.article is CASCADE and
        # StockMovement.article is PROTECT, so an article with stock history
        # cannot be deleted and a deleted one takes its level with it.
        entry = catalogue[level["article_id"]]
        article = {
            "article_id": entry["article_id"],
            "sku": entry["sku"],
            "name": entry["name"],
            "unit": entry["unit"],
            "quantity": level["quantity"],
            # The article's price today. The document states this method in
            # words.
            "purchase_price": entry["purchase_price"],
            "value": level["quantity"] * entry["purchase_price"],
            "reorder_threshold": level["reorder_threshold"],
            "status": derive_stock_status(
                level["quantity"], level["reorder_threshold"]
            ),
        }

        group = groups.get(entry["category_id"])
        if group is None:
            group = {
                "category_id": entry["category_id"],
                "category_name": entry["category_name"],
                "articles": [],
                "value": 0,
            }
            groups[entry["category_id"]] = group
        group["articles"].append(article)
        group["value"] += article["value"]

    categories = sorted(
        groups.values(),
        key=lambda group: (
            collation_key(group["category_name"]),
            str(group["category_id"]),
        ),
    )
    for group in categories:
        group["articles"].sort(
            key=lambda row: (collation_key(row["name"]), str(row["article_id"]))
        )

    totals = {
        "article_count": sum(len(group["articles"]) for group in categories),
        "value": sum(group["value"] for group in categories),
    }
    return categories, totals


def _movement_summary(movements: list[dict]) -> list[dict]:
    summary: dict = {}
    for row in movements:
        key = (row["type"], row["reason"])
        entry = summary.get(key)
        if entry is None:
            entry = {
                "type": row["type"],
                "reason": row["reason"],
                "movement_count": 0,
                "quantity": 0,
            }
            summary[key] = entry
        entry["movement_count"] += 1
        entry["quantity"] += row["quantity"]

    return sorted(
        summary.values(),
        key=lambda row: (
            TYPE_ORDER.index(row["type"]),
            REASON_ORDER.index(row["reason"]),
        ),
    )


def _supplier_purchases(rows: dict, movements: list[dict]) -> list[dict]:
    purchases: dict = {}

    for row in movements:
        if row["type"] != "IN" or row["reason"] != "PURCHASE":
            continue

        supplier_id = (
            rows["supplier_by_transaction"].get(row["transaction_id"])
            if row["transaction_id"]
            else None
        )
        key = supplier_id or NO_SUPPLIER_KEY
        # A purchase with no recorded unit cost contributes ZERO, never the
        # article's current price: valuing it at today's price would rewrite
        # what the period actually cost. The count keeps the omission visible.
        cost = row["quantity"] * (row["unit_cost"] or 0)

        entry = purchases.get(key)
        if entry is None:
            entry = {
                "supplier_id": supplier_id,
                "supplier_name": (
                    rows["supplier_names"].get(supplier_id, NO_SUPPLIER_LABEL)
                    if supplier_id
                    else NO_SUPPLIER_LABEL
                ),
                "movement_count": 0,
                "quantity": 0,
                "cost": 0,
                "without_cost_count": 0,
            }
            purchases[key] = entry
        entry["movement_count"] += 1
        entry["quantity"] += row["quantity"]
        entry["cost"] += cost
        entry["without_cost_count"] += 1 if row["unit_cost"] is None else 0

    return sorted(
        purchases.values(),
        key=lambda row: (-row["cost"], str(row["supplier_id"] or "")),
    )


def _journal(rows: dict, movements: list[dict]) -> list[dict]:
    catalogue = rows["catalogue"]
    return sorted(
        (
            {
                "id": row["id"],
                "created_at": row["created_at"],
                # StockMovement.article is PROTECT: a moved article cannot be
                # deleted, so the lookup cannot miss.
                "article_name": catalogue[row["article_id"]]["name"],
                "article_sku": catalogue[row["article_id"]]["sku"],
                "type": row["type"],
                "reason": row["reason"],
                "quantity": row["quantity"],
                "quantity_before": row["quantity_before"],
                "quantity_after": row["quantity_after"],
                "reference": row["reference"],
                "user_name": row["user_name"],
            }
            for row in movements
        ),
        key=lambda row: (row["created_at"], str(row["id"])),
    )


def build_stock_report(
    rows: dict, tz: ZoneInfo, start: date, end: date, generated_at: datetime
) -> dict:
    categories, stock_totals = _inventory(rows)
    movements = [
        row for row in rows["movements"] if in_range(row["created_at"], tz, start, end)
    ]

    return {
        "meta": report_meta(start, end, generated_at),
        "categories": categories,
        "stock_totals": stock_totals,
        "movement_summary": _movement_summary(movements),
        "supplier_purchases": _supplier_purchases(rows, movements),
        "journal": _journal(rows, movements),
    }
