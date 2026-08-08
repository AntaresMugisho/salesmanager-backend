"""The stock-status rule, in one place.

Mirrors `deriveStatus` in the frontend's `lib/service-utils.ts`. Both
comparisons are inclusive.

This is the canonical encoding. `StockLevel.status` and the stock report both
call it. Two SQL encodings remain — `article_queryset`'s annotation and
`ArticleFilterSet`'s buckets — because neither can call a Python function;
consolidating those needs a shared SQL expression and is tracked as a
follow-up.
"""


def derive_stock_status(quantity: int, threshold: int) -> str:
    if quantity <= 0:
        return "OUT_OF_STOCK"
    if quantity <= threshold:
        return "LOW"
    return "IN_STOCK"
