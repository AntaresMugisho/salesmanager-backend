"""Query-param translation.

`djangorestframework-camel-case` converts request *bodies* only. The
frontend also sends camelCase *query parameters* — `categoryId`, `pageSize`,
`dateFrom` — and camelCase *ordering values* like `-createdAt`. The library
handles the names; the values are this module's job.
"""

import pytest
from django.http import QueryDict
from rest_framework.test import APIRequestFactory
from rest_framework.views import APIView

from apps.common.filters import (
    CamelCaseQueryParamsMixin,
    camel_to_snake,
    underscoreize_ordering,
)


@pytest.mark.parametrize(
    ("camel", "snake"),
    [
        ("createdAt", "created_at"),
        ("categoryId", "category_id"),
        ("stockStatus", "stock_status"),
        ("reorderThreshold", "reorder_threshold"),
        ("name", "name"),
        ("", ""),
    ],
)
def test_camel_to_snake(camel, snake):
    assert camel_to_snake(camel) == snake


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("createdAt", "created_at"),
        ("-createdAt", "-created_at"),
        ("name", "name"),
        ("-name", "-name"),
        ("-createdAt,name", "-created_at,name"),
        ("", ""),
    ],
)
def test_underscoreize_ordering(value, expected):
    """The descending marker must survive translation."""
    assert underscoreize_ordering(value) == expected


class _Probe(CamelCaseQueryParamsMixin, APIView):
    permission_classes = []
    authentication_classes = []
    seen = None

    def get(self, request):
        from rest_framework.response import Response

        type(self).seen = dict(request.query_params.items())
        return Response({})


def call(query_string):
    _Probe.seen = None
    request = APIRequestFactory().get(f"/?{query_string}")
    _Probe.as_view()(request)
    return _Probe.seen


def test_param_names_are_translated():
    assert call("categoryId=abc&pageSize=50") == {
        "category_id": "abc",
        "page_size": "50",
    }


def test_ordering_values_are_translated():
    """The library does NOT do this — it converts names, not values."""
    assert call("ordering=-createdAt")["ordering"] == "-created_at"


def test_already_snake_case_params_are_untouched():
    assert call("date_from=2026-07-01")["date_from"] == "2026-07-01"


def test_values_that_are_not_ordering_are_left_alone():
    """A search term or a status code must never be case-mangled."""
    seen = call("search=Crème&stockStatus=OUT_OF_STOCK")
    assert seen["search"] == "Crème"
    assert seen["stock_status"] == "OUT_OF_STOCK"


def test_underscoreize_returns_a_mutable_query_dict():
    """Guards the assumption `CamelCaseQueryParamsMixin` relies on."""
    from djangorestframework_camel_case.util import underscoreize

    result = underscoreize(QueryDict("a=1").copy())
    result.setlist("b", ["2"])  # must not raise
    assert result["b"] == "2"
