"""The rapport des ventes."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from apps.finance.aggregate import paid_by_sale, summarise
from apps.finance.period import in_range
from apps.reports.meta import report_meta
from apps.sales.totals import compute_balance, group_vat_by_rate

#: Sales with no customer are all folded onto one row under this label.
WALK_IN_LABEL = "Client de passage"

#: Map key for the walk-in group. Not a UUID, so it cannot collide with one.
WALK_IN_KEY = "__walk_in__"

COMPLETED = "COMPLETED"


def build_sales_report(
    facts: dict, tz: ZoneInfo, start: date, end: date, generated_at: datetime
) -> dict:
    # The four figures this report shares with the compte de résultat come from
    # summarise(), not from a second fold, so the two documents cannot disagree
    # about the same period.
    summary = summarise(facts, tz, start, end)
    paid = paid_by_sale(facts["payments"])

    in_period = [
        sale for sale in facts["sales"] if in_range(sale["created_at"], tz, start, end)
    ]
    completed = [sale for sale in in_period if sale["status"] == COMPLETED]
    completed_ids = {sale["id"] for sale in completed}

    invoices = sorted(
        (
            {
                "id": sale["id"],
                "reference": sale["reference"],
                "created_at": sale["created_at"],
                "customer_name": sale["customer_name"] or WALK_IN_LABEL,
                "status": sale["status"],
                "total": sale["total"],
                # The payment stands even on a cancelled sale — the cash moved
                # and there is no refund entity to undo it — but nothing is
                # owed, so an unpaid cancelled invoice must not print a balance.
                "paid": paid.get(sale["id"], 0),
                "balance": compute_balance(
                    sale["total"], paid.get(sale["id"], 0), sale["status"]
                ),
            }
            for sale in in_period
        ),
        # Explicit id tie-break: two sales in the same second must not swap
        # between requests.
        key=lambda row: (row["created_at"], str(row["id"])),
    )

    by_customer: dict = {}
    for sale in completed:
        key = sale["customer_id"] or WALK_IN_KEY
        paid_amount = paid.get(sale["id"], 0)
        row = by_customer.get(key)
        if row is None:
            row = {
                "customer_id": sale["customer_id"],
                "customer_name": sale["customer_name"] or WALK_IN_LABEL,
                "invoice_count": 0,
                "total": 0,
                "paid": 0,
                "balance": 0,
            }
            by_customer[key] = row
        row["invoice_count"] += 1
        row["total"] += sale["total"]
        row["paid"] += paid_amount
        # Floored per sale, so one overpaid invoice cannot cancel out another
        # invoice's debt.
        row["balance"] += max(sale["total"] - paid_amount, 0)

    return {
        "meta": report_meta(start, end, generated_at),
        "totals": {
            "invoice_count": len(completed),
            "cancelled_count": len(in_period) - len(completed),
            "total_ttc": sum(sale["total"] for sale in completed),
            # Already camelCase, deliberately. The contract spells this
            # `revenueHT`, and the renderer's snake_case conversion produces
            # `revenueHt` — which the document reads as undefined. A key with
            # no underscore passes through camelize() untouched, so naming it
            # here is what puts the right spelling on the wire.
            # `totalTtc` above is genuinely lower-case in the contract.
            "revenueHT": summary["revenue"],
            "vat_collected": summary["vat_collected"],
            "discounts": sum(sale["discount"] for sale in completed),
            "receipts": summary["receipts"],
            # As of today, not period-scoped — the document says « à ce jour ».
            "receivables": summary["receivables"],
        },
        "vat": group_vat_by_rate(
            [line for line in facts["lines"] if line["sale_id"] in completed_ids]
        ),
        # Explicit tie-break so two customers with equal totals cannot swap
        # between requests.
        "customers": sorted(
            by_customer.values(),
            key=lambda row: (-row["total"], str(row["customer_id"] or "")),
        ),
        "invoices": invoices,
    }
