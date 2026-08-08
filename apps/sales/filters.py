from django.db.models import F
from django_filters import rest_framework as drf_filters

from apps.common.dates import end_of_day, start_of_day
from apps.sales.models import Sale

PAYMENT_STATUS_CHOICES = [
    ("UNPAID", "UNPAID"),
    ("PARTIAL", "PARTIAL"),
    ("PAID", "PAID"),
]


class SaleFilterSet(drf_filters.FilterSet):
    customer_id = drf_filters.UUIDFilter(field_name="customer_id")
    status = drf_filters.ChoiceFilter(choices=Sale.Status.choices)
    payment_status = drf_filters.ChoiceFilter(
        choices=PAYMENT_STATUS_CHOICES, method="filter_payment_status"
    )
    date_from = drf_filters.DateFilter(method="filter_date_from")
    date_to = drf_filters.DateFilter(method="filter_date_to")

    class Meta:
        model = Sale
        fields = ["customer_id", "status", "payment_status", "date_from", "date_to"]

    def filter_payment_status(self, queryset, name, value):
        # A cancelled sale is not a receivable, so it never matches a payment
        # status filter — otherwise « Impayée » would list sales nobody owes
        # for. Requires the `paid_amount` annotation from sale_queryset().
        queryset = queryset.exclude(status=Sale.Status.CANCELLED)
        if value == "UNPAID":
            return queryset.filter(paid_amount__lte=0)
        if value == "PAID":
            return queryset.filter(paid_amount__gte=F("total"))
        return queryset.filter(paid_amount__gt=0, paid_amount__lt=F("total"))

    def filter_date_from(self, queryset, name, value):
        return queryset.filter(created_at__gte=start_of_day(value))

    def filter_date_to(self, queryset, name, value):
        return queryset.filter(created_at__lte=end_of_day(value))
