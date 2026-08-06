from django_filters import rest_framework as drf_filters

from apps.common.dates import end_of_day, start_of_day
from apps.stock.models import StockMovement, StockTransaction


class MovementFilterSet(drf_filters.FilterSet):
    article_id = drf_filters.UUIDFilter(field_name="article_id")
    type = drf_filters.ChoiceFilter(choices=StockMovement.Type.choices)
    reason = drf_filters.ChoiceFilter(choices=StockMovement.Reason.choices)
    # Bare calendar dates, resolved in SHOP_TIME_ZONE. `date_to` is inclusive
    # of the whole local day, matching the frontend's picker.
    date_from = drf_filters.DateFilter(method="filter_date_from")
    date_to = drf_filters.DateFilter(method="filter_date_to")

    class Meta:
        model = StockMovement
        fields = ["article_id", "type", "reason", "date_from", "date_to"]

    def filter_date_from(self, queryset, name, value):
        return queryset.filter(created_at__gte=start_of_day(value))

    def filter_date_to(self, queryset, name, value):
        return queryset.filter(created_at__lte=end_of_day(value))


class TransactionFilterSet(drf_filters.FilterSet):
    type = drf_filters.ChoiceFilter(choices=StockMovement.Type.choices)
    reason = drf_filters.ChoiceFilter(choices=StockMovement.Reason.choices)
    date_from = drf_filters.DateFilter(method="filter_date_from")
    date_to = drf_filters.DateFilter(method="filter_date_to")

    class Meta:
        model = StockTransaction
        fields = ["type", "reason", "date_from", "date_to"]

    def filter_date_from(self, queryset, name, value):
        return queryset.filter(created_at__gte=start_of_day(value))

    def filter_date_to(self, queryset, name, value):
        return queryset.filter(created_at__lte=end_of_day(value))
