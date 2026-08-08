"""Sale endpoints: create, list, detail."""

import uuid
from datetime import datetime, timezone as dt_timezone

import pytest

from apps.catalogue.tests.factories import ArticleFactory
from apps.sales.models import Sale
from apps.sales.services import create_sale
from apps.sales.tests.factories import CustomerFactory, PaymentFactory
from apps.stock.tests.factories import StockLevelFactory

pytestmark = pytest.mark.django_db

URL = "/api/sales/"


def stocked(site, quantity=100, **kwargs):
    article = ArticleFactory(**kwargs)
    StockLevelFactory(article=article, site=site, quantity=quantity)
    return article


def body(lines, **overrides):
    payload = {
        "customerId": None,
        "discount": 0,
        "discountRate": None,
        "note": None,
        "lines": lines,
    }
    payload.update(overrides)
    return payload


def line(article, quantity=2, unit_price=5_000):
    return {
        "articleId": str(article.id),
        "quantity": quantity,
        "unitPrice": unit_price,
    }


def make(site, user, quantities=(2,), **kwargs):
    lines = [
        {"article": stocked(site), "quantity": q, "unit_price": 5_000}
        for q in quantities
    ]
    return create_sale(lines=lines, user=user, site=site, **kwargs)


class TestCreate:
    def test_a_cashier_can_create_a_sale(self, auth_client, cashier, site):
        """The till. Cashiers create sales and payments; they do not cancel."""
        response = auth_client(cashier).post(
            URL, body([line(stocked(site))]), format="json"
        )
        assert response.status_code == 201
        assert response.json()["reference"].startswith("FA-")

    def test_the_payload_matches_the_frontend_sale_type(
        self, auth_client, cashier, site
    ):
        response = auth_client(cashier).post(
            URL, body([line(stocked(site))]), format="json"
        )

        assert set(response.json()) == {
            "id",
            "reference",
            "siteId",
            "customerId",
            "customer",
            "status",
            "subtotal",
            "discount",
            "discountRate",
            "total",
            "vatTotal",
            "note",
            "cancelledAt",
            "cancelReason",
            "lineCount",
            "paidAmount",
            "balance",
            "paymentStatus",
            "userId",
            "userName",
            "createdAt",
        }

    def test_a_new_sale_is_unpaid_with_the_full_balance(
        self, auth_client, cashier, site
    ):
        response = auth_client(cashier).post(
            URL, body([line(stocked(site), 2, 5_000)]), format="json"
        )
        payload = response.json()
        assert payload["paidAmount"] == 0
        assert payload["balance"] == payload["total"] == 10_000
        assert payload["paymentStatus"] == "UNPAID"

    def test_a_customer_is_recorded_by_id_and_ref(self, auth_client, cashier, site):
        customer = CustomerFactory(name="Kivu Market")
        response = auth_client(cashier).post(
            URL,
            body([line(stocked(site))], customerId=str(customer.id)),
            format="json",
        )
        assert response.json()["customerId"] == str(customer.id)
        assert response.json()["customer"] == {
            "id": str(customer.id),
            "name": "Kivu Market",
        }

    def test_a_walk_in_sale_has_a_null_customer(self, auth_client, cashier, site):
        response = auth_client(cashier).post(
            URL, body([line(stocked(site))]), format="json"
        )
        assert response.json()["customerId"] is None
        assert response.json()["customer"] is None

    def test_line_count_reflects_the_lines(self, auth_client, cashier, site):
        response = auth_client(cashier).post(
            URL, body([line(stocked(site)), line(stocked(site))]), format="json"
        )
        assert response.json()["lineCount"] == 2


class TestCreateValidation:
    def test_no_lines_is_rejected(self, auth_client, cashier, site):
        response = auth_client(cashier).post(URL, body([]), format="json")
        assert response.status_code == 400
        assert response.json()["fieldErrors"]["lines"] == [
            "Ajoutez au moins un article à la vente."
        ]

    def test_a_duplicate_article_is_rejected(self, auth_client, cashier, site):
        article = stocked(site)
        response = auth_client(cashier).post(
            URL, body([line(article), line(article)]), format="json"
        )
        assert response.status_code == 400
        assert response.json()["fieldErrors"]["lines.1.articleId"] == [
            "Cet article est déjà présent dans la vente."
        ]

    def test_an_unknown_article_is_rejected_on_its_row(
        self, auth_client, cashier, site
    ):
        response = auth_client(cashier).post(
            URL,
            body(
                [
                    line(stocked(site)),
                    {"articleId": str(uuid.uuid4()), "quantity": 1, "unitPrice": 100},
                ]
            ),
            format="json",
        )
        assert response.status_code == 400
        assert response.json()["fieldErrors"]["lines.1.articleId"] == [
            "Cet article n'existe plus."
        ]

    def test_a_zero_quantity_is_rejected(self, auth_client, cashier, site):
        """Unlike a stock ADJUSTMENT, a sale line of zero is never meaningful."""
        response = auth_client(cashier).post(
            URL, body([line(stocked(site), quantity=0)]), format="json"
        )
        assert response.status_code == 400
        assert response.json()["fieldErrors"]["lines.0.quantity"] == [
            "La quantité doit être supérieure à zéro."
        ]

    def test_a_negative_unit_price_is_rejected(self, auth_client, cashier, site):
        response = auth_client(cashier).post(
            URL, body([line(stocked(site), unit_price=-1)]), format="json"
        )
        assert response.status_code == 400
        assert response.json()["fieldErrors"]["lines.0.unitPrice"] == [
            "Le prix unitaire est invalide."
        ]

    def test_a_negative_discount_is_rejected(self, auth_client, cashier, site):
        response = auth_client(cashier).post(
            URL, body([line(stocked(site))], discount=-5), format="json"
        )
        assert response.status_code == 400
        assert response.json()["fieldErrors"]["discount"] == [
            "La remise ne peut pas être négative."
        ]

    def test_a_discount_over_the_subtotal_is_rejected(self, auth_client, cashier, site):
        response = auth_client(cashier).post(
            URL, body([line(stocked(site), 1, 1_000)], discount=1_001), format="json"
        )
        assert response.status_code == 400
        assert response.json()["fieldErrors"]["discount"] == [
            "La remise ne peut pas dépasser le total de la vente."
        ]

    def test_insufficient_stock_names_the_offending_row(
        self, auth_client, cashier, site
    ):
        good = stocked(site, quantity=100)
        bad = stocked(site, quantity=1)

        response = auth_client(cashier).post(
            URL, body([line(good, 2), line(bad, 99)]), format="json"
        )

        assert response.status_code == 400
        assert "lines.1.quantity" in response.json()["fieldErrors"]
        assert Sale.objects.count() == 0

    def test_an_unknown_customer_is_rejected(self, auth_client, cashier, site):
        response = auth_client(cashier).post(
            URL,
            body([line(stocked(site))], customerId=str(uuid.uuid4())),
            format="json",
        )
        assert response.status_code == 400
        assert "customerId" in response.json()["fieldErrors"]


class TestList:
    def test_newest_first(self, auth_client, cashier, site, owner):
        first = make(site, owner)
        second = make(site, owner)
        response = auth_client(cashier).get(URL)
        assert [r["id"] for r in response.json()["results"]] == [
            str(second.id),
            str(first.id),
        ]

    def test_the_list_never_includes_lines_or_payments(
        self, auth_client, cashier, site, owner
    ):
        make(site, owner, quantities=(1, 2))
        row = auth_client(cashier).get(URL).json()["results"][0]
        assert "lines" not in row
        assert "payments" not in row

    def test_filter_by_customer(self, auth_client, cashier, site, owner):
        customer = CustomerFactory()
        make(site, owner, customer=customer)
        make(site, owner)
        response = auth_client(cashier).get(f"{URL}?customerId={customer.id}")
        assert response.json()["count"] == 1

    def test_filter_by_status(self, auth_client, cashier, site, owner):
        sale = make(site, owner)
        make(site, owner)
        Sale.objects.filter(pk=sale.pk).update(status="CANCELLED")

        client = auth_client(cashier)
        assert client.get(f"{URL}?status=CANCELLED").json()["count"] == 1
        assert client.get(f"{URL}?status=COMPLETED").json()["count"] == 1

    def test_filter_by_payment_status(self, auth_client, cashier, site, owner):
        unpaid = make(site, owner, quantities=(2,))  # total 10 000
        partial = make(site, owner, quantities=(2,))
        paid = make(site, owner, quantities=(2,))
        PaymentFactory(sale=partial, user=owner, amount=3_000)
        PaymentFactory(sale=paid, user=owner, amount=paid.total)

        client = auth_client(cashier)
        assert [
            r["id"] for r in client.get(f"{URL}?paymentStatus=UNPAID").json()["results"]
        ] == [str(unpaid.id)]
        assert [
            r["id"] for r in client.get(f"{URL}?paymentStatus=PARTIAL").json()["results"]
        ] == [str(partial.id)]
        assert [
            r["id"] for r in client.get(f"{URL}?paymentStatus=PAID").json()["results"]
        ] == [str(paid.id)]

    def test_a_cancelled_sale_never_matches_a_payment_status_filter(
        self, auth_client, cashier, site, owner
    ):
        """Otherwise « Impayée » would list sales nobody owes for."""
        sale = make(site, owner)
        Sale.objects.filter(pk=sale.pk).update(status="CANCELLED")

        client = auth_client(cashier)
        for value in ("UNPAID", "PARTIAL", "PAID"):
            assert client.get(f"{URL}?paymentStatus={value}").json()["count"] == 0

    @pytest.mark.parametrize(
        ("param", "value"),
        [("status", "PENDING"), ("paymentStatus", "MAYBE")],
    )
    def test_an_invalid_filter_value_is_400(
        self, auth_client, cashier, site, param, value
    ):
        response = auth_client(cashier).get(f"{URL}?{param}={value}")
        assert response.status_code == 400
        assert param in response.json()["fieldErrors"]

    def test_search_covers_reference_customer_name_and_note(
        self, auth_client, cashier, site, owner
    ):
        customer = CustomerFactory(name="Kivu Market")
        target = make(site, owner, customer=customer, note="Livraison spéciale")
        make(site, owner)

        client = auth_client(cashier)
        assert client.get(f"{URL}?search={target.reference}").json()["count"] == 1
        assert client.get(f"{URL}?search=kivu").json()["count"] == 1
        assert client.get(f"{URL}?search=spéciale").json()["count"] == 1

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


class TestDateBounds:
    @pytest.fixture(autouse=True)
    def _kinshasa(self, settings):
        settings.SHOP_TIME_ZONE = "Africa/Kinshasa"

    def _at(self, instant, site, owner):
        sale = make(site, owner)
        Sale.objects.filter(pk=sale.pk).update(created_at=instant)
        return sale

    def test_date_from_includes_the_early_local_morning(
        self, auth_client, cashier, site, owner
    ):
        self._at(datetime(2026, 7, 1, 23, 30, tzinfo=dt_timezone.utc), site, owner)
        assert (
            auth_client(cashier).get(f"{URL}?dateFrom=2026-07-02").json()["count"] == 1
        )

    def test_date_to_is_inclusive_of_the_whole_local_day(
        self, auth_client, cashier, site, owner
    ):
        self._at(datetime(2026, 7, 2, 22, 30, tzinfo=dt_timezone.utc), site, owner)
        assert auth_client(cashier).get(f"{URL}?dateTo=2026-07-02").json()["count"] == 1


class TestDetail:
    def test_the_payload_adds_lines_and_payments(
        self, auth_client, cashier, site, owner
    ):
        sale = make(site, owner, quantities=(1, 2))
        PaymentFactory(sale=sale, user=owner, amount=1_000)

        payload = auth_client(cashier).get(f"{URL}{sale.id}/").json()

        assert len(payload["lines"]) == 2
        assert len(payload["payments"]) == 1
        assert set(payload["lines"][0]) == {
            "id",
            "articleId",
            "articleName",
            "articleSku",
            "unit",
            "quantity",
            "unitPrice",
            "unitCost",
            "vatRate",
            "lineTotal",
            "discountShare",
            "vatAmount",
        }
        assert set(payload["payments"][0]) == {
            "id",
            "saleId",
            "amount",
            "method",
            "paidAt",
            "reference",
            "note",
            "userId",
            "userName",
            "createdAt",
        }

    def test_the_detail_customer_carries_the_billing_block(
        self, auth_client, cashier, site, owner
    ):
        customer = CustomerFactory(
            name="Kivu Market", address="10 av. du Lac", tax_number="A123"
        )
        sale = make(site, owner, customer=customer)

        payload = auth_client(cashier).get(f"{URL}{sale.id}/").json()

        assert payload["customer"] == {
            "id": str(customer.id),
            "name": "Kivu Market",
            "address": "10 av. du Lac",
            "taxNumber": "A123",
        }

    def test_lines_are_sorted_by_article_name_in_french(
        self, auth_client, cashier, site, owner
    ):
        """Python's default sort puts « Épicerie » after « Zzz » because É is
        U+00C9. French collation puts it beside E."""
        lines = [
            {"article": stocked(site, name="Zèbre"), "quantity": 1, "unit_price": 100},
            {
                "article": stocked(site, name="Épicerie"),
                "quantity": 1,
                "unit_price": 100,
            },
            {"article": stocked(site, name="Avocat"), "quantity": 1, "unit_price": 100},
        ]
        sale = create_sale(lines=lines, user=owner, site=site)

        payload = auth_client(cashier).get(f"{URL}{sale.id}/").json()

        assert [row["articleName"] for row in payload["lines"]] == [
            "Avocat",
            "Épicerie",
            "Zèbre",
        ]

    def test_unknown_id_is_404_with_the_envelope(self, auth_client, cashier, site):
        response = auth_client(cashier).get(f"{URL}{uuid.uuid4()}/")
        assert response.status_code == 404
        assert response.json()["code"] == "not_found"
