"""The reports' ORM seam.

The only file in `apps.reports` that touches the database. Everything the four
builders need beyond `apps.finance.facts.load_facts`, projected with `.values()`
into plain dicts.

Not range-filtered, for the same reason as the finance seam: the inventory half
of the stock report is as-of-now, and the period-scoped folds filter in Python
through `in_range`.
"""

from apps.catalogue.models import Article, Supplier
from apps.stock.models import StockLevel, StockMovement, StockTransaction


def load_report_facts(site) -> dict:
    """Read every extra row the four reports fold, once."""
    catalogue = {
        row["id"]: {
            "article_id": row["id"],
            "sku": row["sku"],
            "name": row["name"],
            "unit": row["unit"],
            "purchase_price": row["purchase_price"],
            "category_id": row["category_id"],
            "category_name": row["category__name"],
        }
        # Not site-scoped: articles and categories carry no site of their own.
        # `values()` spanning the FK does the join itself, so no select_related.
        for row in Article.objects.values(
            "id",
            "sku",
            "name",
            "unit",
            "purchase_price",
            "category_id",
            "category__name",
        )
    }

    return {
        "catalogue": catalogue,
        "levels": list(
            StockLevel.objects.filter(site=site).values(
                "article_id", "quantity", "reorder_threshold"
            )
        ),
        "movements": list(
            StockMovement.objects.filter(site=site).values(
                "id",
                "created_at",
                "article_id",
                "type",
                "reason",
                "quantity",
                "quantity_before",
                "quantity_after",
                "unit_cost",
                "reference",
                "transaction_id",
                "user_name",
            )
        ),
        # A movement carries no supplier of its own; its transaction does, and
        # an article's default supplier is not necessarily who a given purchase
        # came from.
        "supplier_by_transaction": dict(
            StockTransaction.objects.filter(site=site).values_list("id", "supplier_id")
        ),
        # The *current* name, matching the frontend, which resolves supplier
        # names from the suppliers table rather than the transaction's snapshot.
        "supplier_names": dict(Supplier.objects.values_list("id", "name")),
    }
