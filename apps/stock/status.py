"""The stock-status rule, in one place.

Two encodings of this rule exist and must agree:

1. `derive_stock_status` below — called by `StockLevel.status`, by the stock
   report, and by `StockSummarySerializer.get_status`.
2. `ArticleFilterSet.filter_stock_status` — the same boundaries in SQL, which
   cannot call a Python function.

Consolidating them needs a shared SQL expression and is tracked as a
follow-up. The tests assert the same boundaries in each.

(An earlier version of this docstring named `article_queryset`'s annotation as
a second encoding. That annotation computes `stock_quantity` and
`stock_threshold` and derives no status, and there is no `deriveStatus` in the
frontend either — it reads `stock.status` from the API.)
"""


def derive_stock_status(quantity: int, threshold: int) -> str:
    # Below zero first: a negative level also satisfies `<= 0`, so the order of
    # these two branches is what distinguishes "the books are wrong" from
    # "the shelf is empty". The same ordering is required in the SQL filter.
    if quantity < 0:
        return "NEGATIVE"
    if quantity <= 0:
        return "OUT_OF_STOCK"
    if quantity <= threshold:
        return "LOW"
    return "IN_STOCK"
