"""The annotated article queryset.

`?stockStatus=` and `ordering=stock` both need the quantity in SQL, and the
serializer needs it in the payload. Doing it once as an annotation serves all
three and keeps the query count flat; composing `stock` from the related
object instead costs one query per row.
"""

from django.db.models import IntegerField, OuterRef, QuerySet, Subquery
from django.db.models.functions import Coalesce

from apps.accounts.models import Site
from apps.catalogue.models import Article


def article_queryset(site=None) -> QuerySet[Article]:
    # Imported inside the function on purpose. `apps.stock` imports from
    # `apps.catalogue` — a module-level import here would close that cycle
    # the moment apps/stock/serializers.py imports ArticleRefSerializer.
    from apps.stock.models import StockLevel

    # Callers that also need the site for serializer context pass it in, so a
    # single request resolves the singleton once instead of twice.
    if site is None:
        site = Site.objects.current()
    levels = StockLevel.objects.filter(article=OuterRef("pk"), site=site)

    return Article.objects.select_related("category", "supplier").annotate(
        stock_quantity=Coalesce(
            Subquery(levels.values("quantity")[:1]),
            0,
            output_field=IntegerField(),
        ),
        stock_threshold=Coalesce(
            Subquery(levels.values("reorder_threshold")[:1]),
            0,
            output_field=IntegerField(),
        ),
    )
