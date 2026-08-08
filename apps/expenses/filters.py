from django_filters import rest_framework as drf_filters

from apps.common.dates import end_of_day, start_of_day
from apps.expenses.models import Expense


class ExpenseFilterSet(drf_filters.FilterSet):
    category = drf_filters.ChoiceFilter(choices=Expense.Category.choices)
    date_from = drf_filters.DateFilter(method="filter_date_from")
    date_to = drf_filters.DateFilter(method="filter_date_to")

    class Meta:
        model = Expense
        fields = ["category", "date_from", "date_to"]

    def filter_date_from(self, queryset, name, value):
        return queryset.filter(spent_at__gte=start_of_day(value))

    def filter_date_to(self, queryset, name, value):
        return queryset.filter(spent_at__lte=end_of_day(value))
