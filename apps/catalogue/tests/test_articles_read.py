"""Article reads: payload, filters, ordering, and query counts."""

import pytest

from apps.catalogue.tests.factories import (
    ArticleFactory,
    CategoryFactory,
    SupplierFactory,
)
from apps.stock.tests.factories import StockLevelFactory

pytestmark = pytest.mark.django_db

LIST_URL = "/api/articles/"


def detail_url(article) -> str:
    return f"{LIST_URL}{article.id}/"


class TestPayload:
    def test_matches_the_frontend_article_type(self, auth_client, cashier, site):
        category = CategoryFactory(name="Boissons")
        supplier = SupplierFactory(name="Brasimba")
        article = ArticleFactory(category=category, supplier=supplier)
        StockLevelFactory(article=article, site=site, quantity=5, reorder_threshold=10)

        response = auth_client(cashier).get(LIST_URL)

        assert response.status_code == 200
        row = response.json()["results"][0]
        assert set(row) == {
            "id",
            "sku",
            "barcode",
            "name",
            "description",
            "categoryId",
            "category",
            "supplierId",
            "supplier",
            "unit",
            "purchasePrice",
            "salePrice",
            "vatRate",
            "isActive",
            "imageUrl",
            "stock",
            "createdAt",
            "updatedAt",
        }
        assert set(row["category"]) == {"id", "name"}
        assert set(row["supplier"]) == {"id", "name"}
        assert set(row["stock"]) == {"siteId", "quantity", "reorderThreshold", "status"}
        assert row["category"]["name"] == "Boissons"
        assert row["supplier"]["name"] == "Brasimba"
        assert row["stock"]["quantity"] == 5
        assert row["stock"]["reorderThreshold"] == 10
        assert row["stock"]["status"] == "LOW"

    def test_vat_rate_is_a_number_not_a_string(self, auth_client, cashier, site):
        """`COERCE_DECIMAL_TO_STRING = False`.

        DRF's default renders a DecimalField as "16.00", and the frontend's
        `vatRate: number` then renders NaN in the article form.
        """
        from decimal import Decimal

        ArticleFactory(vat_rate=Decimal("16.00"))
        row = auth_client(cashier).get(LIST_URL).json()["results"][0]
        assert isinstance(row["vatRate"], float)
        assert row["vatRate"] == 16.0

    def test_a_null_supplier_serialises_as_null(self, auth_client, cashier, site):
        ArticleFactory(supplier=None)
        row = auth_client(cashier).get(LIST_URL).json()["results"][0]
        assert row["supplier"] is None
        assert row["supplierId"] is None

    def test_an_article_with_no_level_reads_as_zero(self, auth_client, cashier, site):
        """Coalesced to 0, not omitted. The frontend's `composeArticles` does
        the same with `level?.quantity ?? 0`."""
        ArticleFactory()
        row = auth_client(cashier).get(LIST_URL).json()["results"][0]
        assert row["stock"]["quantity"] == 0
        assert row["stock"]["status"] == "OUT_OF_STOCK"

    def test_site_id_is_the_current_site(self, auth_client, cashier, site):
        ArticleFactory()
        row = auth_client(cashier).get(LIST_URL).json()["results"][0]
        assert row["stock"]["siteId"] == str(site.id)


class TestFilters:
    def test_by_category(self, auth_client, cashier, site):
        wanted = CategoryFactory()
        ArticleFactory(category=wanted)
        ArticleFactory(category=CategoryFactory())

        response = auth_client(cashier).get(f"{LIST_URL}?categoryId={wanted.id}")
        assert response.json()["count"] == 1

    def test_by_supplier(self, auth_client, cashier, site):
        wanted = SupplierFactory()
        ArticleFactory(supplier=wanted)
        ArticleFactory(supplier=None)

        response = auth_client(cashier).get(f"{LIST_URL}?supplierId={wanted.id}")
        assert response.json()["count"] == 1

    def test_by_is_active(self, auth_client, cashier, site):
        ArticleFactory(is_active=True)
        ArticleFactory(is_active=False)
        client = auth_client(cashier)

        assert client.get(f"{LIST_URL}?isActive=true").json()["count"] == 1
        assert client.get(f"{LIST_URL}?isActive=false").json()["count"] == 1

    @pytest.mark.parametrize("status", ["OUT_OF_STOCK", "LOW", "IN_STOCK"])
    def test_by_stock_status(self, auth_client, cashier, site, status):
        for quantity, threshold in [(0, 10), (5, 10), (50, 10)]:
            article = ArticleFactory()
            StockLevelFactory(
                article=article,
                site=site,
                quantity=quantity,
                reorder_threshold=threshold,
            )

        response = auth_client(cashier).get(f"{LIST_URL}?stockStatus={status}")

        assert response.json()["count"] == 1
        assert response.json()["results"][0]["stock"]["status"] == status

    def test_search_covers_name_sku_and_barcode(self, auth_client, cashier, site):
        ArticleFactory(name="Sucre blanc", sku="EPI-001", barcode="1234567890123")
        ArticleFactory(name="Farine", sku="EPI-002", barcode="9876543210987")
        client = auth_client(cashier)

        assert client.get(f"{LIST_URL}?search=sucre").json()["count"] == 1
        assert client.get(f"{LIST_URL}?search=EPI-002").json()["count"] == 1
        assert client.get(f"{LIST_URL}?search=1234567890123").json()["count"] == 1

    @pytest.mark.parametrize(
        ("param", "value"),
        [
            ("isActive", "banana"),
            ("stockStatus", "LOW_ISH"),
            ("categoryId", "not-a-uuid"),
        ],
    )
    def test_an_invalid_filter_value_is_400(
        self, auth_client, cashier, site, param, value
    ):
        """A dropped filter returns *more* rows than asked for while looking
        like a correct response. That is why these must error."""
        response = auth_client(cashier).get(f"{LIST_URL}?{param}={value}")

        assert response.status_code == 400
        assert response.json()["code"] == "validation_error"
        assert param in response.json()["fieldErrors"]


class TestOrdering:
    def test_default_is_by_name(self, auth_client, cashier, site):
        ArticleFactory(name="Sucre")
        ArticleFactory(name="Farine")
        response = auth_client(cashier).get(LIST_URL)
        assert [r["name"] for r in response.json()["results"]] == ["Farine", "Sucre"]

    @pytest.mark.parametrize("key", ["name", "sku", "createdAt", "salePrice"])
    def test_each_key_sorts_both_ways(self, auth_client, cashier, site, key):
        ArticleFactory(name="Aaa", sku="AAA-1", sale_price=100)
        ArticleFactory(name="Zzz", sku="ZZZ-9", sale_price=900)
        client = auth_client(cashier)

        ascending = client.get(f"{LIST_URL}?ordering={key}").json()["results"]
        descending = client.get(f"{LIST_URL}?ordering=-{key}").json()["results"]

        assert [r["id"] for r in ascending] == [r["id"] for r in descending][::-1]

    def test_ordering_by_stock_uses_the_annotation(self, auth_client, cashier, site):
        """`stock` is the public sort key; `stock_quantity` is the annotation.
        DRF cannot express that mapping, which is why AliasedOrderingFilter
        exists."""
        low = ArticleFactory(name="Peu")
        high = ArticleFactory(name="Beaucoup")
        StockLevelFactory(article=low, site=site, quantity=1)
        StockLevelFactory(article=high, site=site, quantity=99)

        response = auth_client(cashier).get(f"{LIST_URL}?ordering=stock")

        assert [r["name"] for r in response.json()["results"]] == ["Peu", "Beaucoup"]

    def test_camel_case_ordering_is_translated(self, auth_client, cashier, site):
        ArticleFactory(name="Aaa")
        ArticleFactory(name="Zzz")
        response = auth_client(cashier).get(f"{LIST_URL}?ordering=-createdAt")
        assert response.status_code == 200
        assert [r["name"] for r in response.json()["results"]] == ["Zzz", "Aaa"]

    def test_an_unknown_ordering_key_is_400(self, auth_client, cashier, site):
        """DRF drops it silently and falls back to the default. We do not."""
        response = auth_client(cashier).get(f"{LIST_URL}?ordering=couleur")
        assert response.status_code == 400
        assert "ordering" in response.json()["fieldErrors"]


class TestQueryCount:
    def test_the_list_does_not_scale_with_page_size(
        self, auth_client, cashier, site, django_assert_num_queries
    ):
        """Guards the annotation approach. Composing `stock` from the related
        object instead would issue one extra query per row, and nothing else
        in the suite would notice."""
        for _ in range(10):
            article = ArticleFactory(supplier=SupplierFactory())
            StockLevelFactory(article=article, site=site, quantity=5)

        client = auth_client(cashier)
        client.get(LIST_URL)  # warm any lazily-cached state

        with django_assert_num_queries(4):
            # 1 user, 1 site, 1 count, 1 page
            response = client.get(f"{LIST_URL}?pageSize=10")

        assert len(response.json()["results"]) == 10
