"""GET /api/stock/transactions/ and its detail route."""

import uuid
from datetime import datetime, timezone as dt_timezone

import pytest

from apps.catalogue.tests.factories import ArticleFactory, SupplierFactory
from apps.stock.models import StockTransaction
from apps.stock.services import create_transaction
from apps.stock.tests.factories import StockLevelFactory

pytestmark = pytest.mark.django_db

URL = "/api/stock/transactions/"


def make(site, user, quantities=(5,), **kwargs):
    lines = [
        {"article": ArticleFactory(), "quantity": q, "unit_cost": 800}
        for q in quantities
    ]
    payload = {
        "type": "IN",
        "reason": "PURCHASE",
        "lines": lines,
        "user": user,
        "site": site,
    }
    payload.update(kwargs)
    return create_transaction(**payload)


class TestList:
    def test_the_row_matches_the_frontend_type(self, auth_client, cashier, site, owner):
        make(site, owner)

        response = auth_client(cashier).get(URL)

        assert response.status_code == 200
        assert set(response.json()["results"][0]) == {
            "id",
            "reference",
            "siteId",
            "userReference",
            "type",
            "reason",
            "supplierId",
            "supplierName",
            "note",
            "lineCount",
            "totalQuantity",
            "userId",
            "userName",
            "createdAt",
        }

    def test_the_list_never_includes_lines(self, auth_client, cashier, site, owner):
        """That is what lineCount and totalQuantity are denormalised for."""
        make(site, owner, quantities=(1, 2, 3))
        assert "lines" not in auth_client(cashier).get(URL).json()["results"][0]

    def test_newest_first(self, auth_client, cashier, site, owner):
        first = make(site, owner)
        second = make(site, owner)

        response = auth_client(cashier).get(URL)

        assert [r["id"] for r in response.json()["results"]] == [
            str(second.id),
            str(first.id),
        ]

    def test_filter_by_type_and_reason(self, auth_client, cashier, site, owner):
        make(site, owner, type="IN", reason="PURCHASE")
        make(site, owner, type="ADJUSTMENT", reason="COUNT_CORRECTION")
        client = auth_client(cashier)

        assert client.get(f"{URL}?type=ADJUSTMENT").json()["count"] == 1
        assert client.get(f"{URL}?reason=PURCHASE").json()["count"] == 1

    @pytest.mark.parametrize(
        ("param", "value"), [("type", "SIDEWAYS"), ("reason", "PARCE_QUE")]
    )
    def test_an_invalid_filter_value_is_400(
        self, auth_client, cashier, site, param, value
    ):
        response = auth_client(cashier).get(f"{URL}?{param}={value}")
        assert response.status_code == 400
        assert param in response.json()["fieldErrors"]

    def test_search_covers_all_four_fields(self, auth_client, cashier, site, owner):
        supplier = SupplierFactory(name="Brasimba")
        make(site, owner, supplier=supplier, user_reference="BL-42", note="Matin")
        make(site, owner)
        client = auth_client(cashier)

        assert client.get(f"{URL}?search=BL-42").json()["count"] == 1
        assert client.get(f"{URL}?search=brasimba").json()["count"] == 1
        assert client.get(f"{URL}?search=matin").json()["count"] == 1

        reference = StockTransaction.objects.order_by("created_at").first().reference
        assert client.get(f"{URL}?search={reference}").json()["count"] == 1

    def test_the_query_count_is_flat(
        self, auth_client, cashier, site, owner, django_assert_num_queries
    ):
        for _ in range(10):
            make(site, owner)

        client = auth_client(cashier)
        client.get(URL)

        with django_assert_num_queries(3):
            response = client.get(f"{URL}?pageSize=10")

        assert len(response.json()["results"]) == 10

    def test_a_cashier_may_read(self, auth_client, cashier, site, owner):
        make(site, owner)
        assert auth_client(cashier).get(URL).status_code == 200


class TestDateBounds:
    """Kinshasa is UTC+1, so a transaction at 00h30 local is 23h30 UTC the
    previous day. These fail against a UTC implementation."""

    @pytest.fixture(autouse=True)
    def _kinshasa(self, settings):
        settings.SHOP_TIME_ZONE = "Africa/Kinshasa"

    def _at(self, instant, site, owner):
        header = make(site, owner)
        StockTransaction.objects.filter(pk=header.pk).update(created_at=instant)
        return header

    def test_date_from_includes_the_early_local_morning(
        self, auth_client, cashier, site, owner
    ):
        self._at(datetime(2026, 7, 1, 23, 30, tzinfo=dt_timezone.utc), site, owner)
        response = auth_client(cashier).get(f"{URL}?dateFrom=2026-07-02")
        assert response.json()["count"] == 1

    def test_date_from_excludes_the_previous_local_day(
        self, auth_client, cashier, site, owner
    ):
        self._at(datetime(2026, 7, 1, 22, 30, tzinfo=dt_timezone.utc), site, owner)
        response = auth_client(cashier).get(f"{URL}?dateFrom=2026-07-02")
        assert response.json()["count"] == 0

    def test_date_to_is_inclusive_of_the_whole_local_day(
        self, auth_client, cashier, site, owner
    ):
        self._at(datetime(2026, 7, 2, 22, 30, tzinfo=dt_timezone.utc), site, owner)
        response = auth_client(cashier).get(f"{URL}?dateTo=2026-07-02")
        assert response.json()["count"] == 1


class TestDetail:
    def test_the_payload_adds_lines(self, auth_client, cashier, site, owner):
        header = make(site, owner, quantities=(4, 6))

        response = auth_client(cashier).get(f"{URL}{header.id}/")

        assert response.status_code == 200
        payload = response.json()
        assert "lines" in payload
        assert len(payload["lines"]) == 2
        assert set(payload["lines"][0]) == {
            "movementId",
            "article",
            "quantity",
            "quantityBefore",
            "quantityAfter",
            "unitCost",
        }
        assert set(payload["lines"][0]["article"]) == {"id", "sku", "name", "unit"}

    def test_the_line_figures_come_from_the_movement(
        self, auth_client, cashier, site, owner
    ):
        article = ArticleFactory()
        StockLevelFactory(article=article, site=site, quantity=10)
        header = create_transaction(
            type="IN",
            reason="PURCHASE",
            lines=[{"article": article, "quantity": 5, "unit_cost": 800}],
            user=owner,
            site=site,
        )

        row = auth_client(cashier).get(f"{URL}{header.id}/").json()["lines"][0]

        assert row["quantity"] == 5
        assert row["quantityBefore"] == 10
        assert row["quantityAfter"] == 15
        assert row["unitCost"] == 800

    def test_lines_are_in_a_stable_order(self, auth_client, cashier, site, owner):
        header = make(site, owner, quantities=(1, 2, 3))

        first = auth_client(cashier).get(f"{URL}{header.id}/").json()["lines"]
        second = auth_client(cashier).get(f"{URL}{header.id}/").json()["lines"]

        assert [row["movementId"] for row in first] == [
            row["movementId"] for row in second
        ]

    def test_unknown_id_is_404_with_the_envelope(self, auth_client, cashier, site):
        response = auth_client(cashier).get(f"{URL}{uuid.uuid4()}/")
        assert response.status_code == 404
        assert response.json()["code"] == "not_found"

    def test_the_detail_query_count_is_flat(
        self, auth_client, cashier, site, owner, django_assert_num_queries
    ):
        header = make(site, owner, quantities=tuple(range(1, 11)))

        client = auth_client(cashier)
        client.get(f"{URL}{header.id}/")

        with django_assert_num_queries(3):
            # 1 user, 1 header, 1 lines-with-article — the select_related on
            # the lines query is what keeps this from growing.
            response = client.get(f"{URL}{header.id}/")

        assert len(response.json()["lines"]) == 10
