from django.db.models import F, Q
from django_filters import rest_framework as drf_filters

from apps.catalogue.models import Article
from apps.common.filters import StrictBooleanFilter

STOCK_STATUS_CHOICES = [
    ("IN_STOCK", "IN_STOCK"),
    ("LOW", "LOW"),
    ("OUT_OF_STOCK", "OUT_OF_STOCK"),
]


class ArticleFilterSet(drf_filters.FilterSet):
    category_id = drf_filters.UUIDFilter(field_name="category_id")
    supplier_id = drf_filters.UUIDFilter(field_name="supplier_id")
    is_active = StrictBooleanFilter()
    stock_status = drf_filters.ChoiceFilter(
        choices=STOCK_STATUS_CHOICES, method="filter_stock_status"
    )

    class Meta:
        model = Article
        fields = ["category_id", "supplier_id", "is_active", "stock_status"]

    def filter_stock_status(self, queryset, name, value):
        # The same three inclusive boundaries as StockLevel.status, in SQL.
        if value == "OUT_OF_STOCK":
            return queryset.filter(stock_quantity__lte=0)
        if value == "LOW":
            return queryset.filter(
                stock_quantity__gt=0, stock_quantity__lte=F("stock_threshold")
            )
        return queryset.filter(
            Q(stock_quantity__gt=0) & Q(stock_quantity__gt=F("stock_threshold"))
        )
