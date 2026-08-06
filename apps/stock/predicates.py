"""Shared low-stock definition.

The dashboard tile links to the low-stock list. If they compute membership
separately they will eventually disagree, and the user sees a badge saying 4
above a list showing 3. One function, two callers.
"""

from django.db.models import F, Q, QuerySet


def low_stock_queryset(queryset: QuerySet) -> QuerySet:
    """Active articles that are out of stock or at or below their threshold.

    Expects the `stock_quantity` / `stock_threshold` annotations from
    `apps.catalogue.querysets.article_queryset`.

    Archived articles never count: `isLowStockArticle` in the frontend checks
    `isActive` first, and an archived article is not something to reorder.
    """
    return queryset.filter(
        Q(is_active=True)
        & (Q(stock_quantity__lte=0) | Q(stock_quantity__lte=F("stock_threshold")))
    )
