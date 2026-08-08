"""The ORM seam.

The only file in `apps.finance` that touches the database. It projects five
narrow shapes with `.values()` and hands them to the pure modules as plain
dicts — deliberately not the domain types, because every field named here is
one the arithmetic actually reads.
"""

from apps.expenses.models import Expense
from apps.sales.models import Payment, Sale, SaleLine
from apps.stock.models import StockMovement


def load_facts(site) -> dict:
    """Read every row the three finance endpoints fold, once.

    Not range-filtered, deliberately: `receivables` and `unpaid_sales` need
    every completed sale whenever it happened, and the period-scoped folds
    filter in Python through `in_range`, so the inclusive-bounds rule lives in
    one tested place. Range-filtering this queryset would silently turn both
    of those into period figures without changing a single payload key.

    `SaleLine` and `Payment` carry no site of their own, so they are narrowed
    through the sales that do.
    """
    sales = list(
        Sale.objects.filter(site=site).values(
            "id",
            "created_at",
            "status",
            "total",
            "vat_total",
            "reference",
            "customer_name",
        )
    )
    sale_ids = [row["id"] for row in sales]

    return {
        "sales": sales,
        "lines": list(
            SaleLine.objects.filter(sale_id__in=sale_ids).values(
                "sale_id",
                "article_id",
                "article_name",
                "article_sku",
                "quantity",
                "line_total",
                "discount_share",
                "vat_amount",
                "unit_cost",
            )
        ),
        "payments": list(
            Payment.objects.filter(sale_id__in=sale_ids).values(
                "sale_id",
                "amount",
                "paid_at",
            )
        ),
        "expenses": list(
            Expense.objects.filter(site=site).values(
                "category",
                "amount",
                "spent_at",
            )
        ),
        "purchases": list(
            StockMovement.objects.filter(
                site=site,
                type=StockMovement.Type.IN,
                reason=StockMovement.Reason.PURCHASE,
            ).values("quantity", "unit_cost", "created_at")
        ),
    }
