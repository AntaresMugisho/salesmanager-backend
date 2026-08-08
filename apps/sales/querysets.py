"""The annotated sale queryset.

`paidAmount`, `balance` and `paymentStatus` are derived on every read and
never stored. A status column would be a second source of truth, free to
disagree with the payments it claims to summarise.
"""

from django.db.models import Count, IntegerField, OuterRef, QuerySet, Subquery, Sum
from django.db.models.functions import Coalesce

from apps.sales.models import Payment, Sale


def sale_queryset() -> QuerySet[Sale]:
    """Annotate `paid_amount` and `line_count`.

    `paid_amount` is a correlated subquery rather than `Sum("payments__amount")`
    on purpose. Two join aggregates in one queryset multiply each other's rows:
    a sale with three lines and two payments would report a line count of six
    and three times its true paid amount. The subquery form cannot do that
    because it never joins.

    The explicit `order_by` is **not** redundant with `Sale.Meta.ordering`.
    Django drops `Meta.ordering` from any query carrying a GROUP BY, and
    `Count("lines")` introduces one — so without this the list comes back in
    arbitrary order and pagination can drop or repeat rows between pages. DRF
    only warns (`UnorderedObjectListWarning`) and serves the wrong page anyway.
    """
    paid = (
        Payment.objects.filter(sale=OuterRef("pk"))
        .values("sale")
        .annotate(total=Sum("amount"))
        .values("total")
    )

    return (
        Sale.objects.select_related("customer", "site", "user")
        .annotate(
            paid_amount=Coalesce(
                Subquery(paid, output_field=IntegerField()),
                0,
                output_field=IntegerField(),
            ),
            line_count=Count("lines", distinct=True),
        )
        .order_by("-created_at", "-id")
    )
