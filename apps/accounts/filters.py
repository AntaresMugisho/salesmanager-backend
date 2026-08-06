from django_filters import rest_framework as drf_filters

from apps.accounts.models import User
from apps.common.filters import StrictBooleanFilter


class UserFilterSet(drf_filters.FilterSet):
    is_active = StrictBooleanFilter()

    class Meta:
        model = User
        fields = ["is_active"]
