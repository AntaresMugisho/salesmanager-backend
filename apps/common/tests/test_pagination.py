"""The envelope is exactly { count, next, previous, results }."""

from rest_framework.test import APIRequestFactory

from apps.common.pagination import StandardPagination


def paginate(query_string, items):
    paginator = StandardPagination()
    request_factory = APIRequestFactory()
    from rest_framework.request import Request

    request = Request(request_factory.get(f"/?{query_string}"))
    page = paginator.paginate_queryset(items, request)
    return paginator, page


def test_default_page_size_matches_the_frontend():
    _, page = paginate("", list(range(100)))
    assert len(page) == 20


def test_page_size_param_in_snake_case():
    _, page = paginate("page_size=5", list(range(100)))
    assert len(page) == 5


def test_page_size_param_in_camel_case():
    """Works even on a view that forgot CamelCaseQueryParamsMixin."""
    _, page = paginate("pageSize=5", list(range(100)))
    assert len(page) == 5


def test_page_size_is_capped():
    _, page = paginate("pageSize=5000", list(range(1000)))
    assert len(page) == 500


def test_the_cap_admits_the_largest_page_the_frontend_asks_for():
    """`pageSize: 500` appears in three frontend components that need every
    active article at once. Capping below it truncates silently."""
    _, page = paginate("pageSize=500", list(range(1000)))
    assert len(page) == 500


def test_nonsense_page_size_falls_back_to_the_default():
    _, page = paginate("pageSize=abc", list(range(100)))
    assert len(page) == 20


def test_envelope_shape():
    paginator, page = paginate("", list(range(100)))
    body = paginator.get_paginated_response(page).data
    assert set(body) == {"count", "next", "previous", "results"}
    assert body["count"] == 100
    assert body["previous"] is None
    assert body["next"].startswith("http")
