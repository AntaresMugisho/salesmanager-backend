"""POST /api/sales/{id}/payments/."""

import uuid
from datetime import datetime, timezone as dt_timezone

import pytest

from apps.catalogue.tests.factories import ArticleFactory
from apps.sales.models import Payment, Sale
from apps.sales.services import create_sale
from apps.stock.tests.factories import StockLevelFactory

pytestmark = pytest.mark.django_db


def stocked(site, quantity=100):
    article = ArticleFactory()
    StockLevelFactory(article=article, site=site, quantity=quantity)
    return article


def make(site, user, unit_price=5_000, quantity=2):
    return create_sale(
        lines=[
            {"article": stocked(site), "quantity": quantity, "unit_price": unit_price}
        ],
        user=user,
        site=site,
    )


def url(sale):
    return f"/api/sales/{sale.id}/payments/"


def body(**overrides):
    payload = {
        "amount": 3_000,
        "method": "CASH",
        "paidAt": "2026-07-02",
        "reference": None,
        "note": None,
    }
    payload.update(overrides)
    return payload


class TestCreate:
    def test_a_cashier_can_record_a_payment(self, auth_client, cashier, site, owner):
        sale = make(site, owner)
        response = auth_client(cashier).post(url(sale), body(), format="json")

        assert response.status_code == 201
        assert response.json()["amount"] == 3_000
        assert Payment.objects.count() == 1

    def test_the_payload_matches_the_frontend_payment_type(
        self, auth_client, cashier, site, owner
    ):
        sale = make(site, owner)
        response = auth_client(cashier).post(url(sale), body(), format="json")

        assert set(response.json()) == {
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

    def test_paid_at_is_widened_to_local_noon(
        self, auth_client, cashier, site, owner, settings
    ):
        """The picker gives a bare date. Noon, not midnight, so the stored
        instant lands on the day the user picked whatever the offset."""
        settings.SHOP_TIME_ZONE = "Africa/Kinshasa"
        sale = make(site, owner)

        auth_client(cashier).post(url(sale), body(paidAt="2026-07-02"), format="json")

        # Kinshasa is UTC+1, so local noon is 11:00 UTC.
        assert Payment.objects.get().paid_at == datetime(
            2026, 7, 2, 11, 0, tzinfo=dt_timezone.utc
        )

    def test_the_sale_reflects_the_payment(self, auth_client, cashier, site, owner):
        sale = make(site, owner)  # total 10 000
        auth_client(cashier).post(url(sale), body(amount=3_000), format="json")

        payload = auth_client(cashier).get(f"/api/sales/{sale.id}/").json()
        assert payload["paidAmount"] == 3_000
        assert payload["balance"] == 7_000
        assert payload["paymentStatus"] == "PARTIAL"

    def test_paying_the_balance_marks_it_paid(self, auth_client, cashier, site, owner):
        sale = make(site, owner)
        auth_client(cashier).post(url(sale), body(amount=sale.total), format="json")

        payload = auth_client(cashier).get(f"/api/sales/{sale.id}/").json()
        assert payload["balance"] == 0
        assert payload["paymentStatus"] == "PAID"

    def test_the_user_name_is_snapshotted(self, auth_client, cashier, site, owner):
        sale = make(site, owner)
        auth_client(cashier).post(url(sale), body(), format="json")
        assert Payment.objects.get().user_name == cashier.full_name


class TestValidation:
    def test_a_zero_amount_is_rejected(self, auth_client, cashier, site, owner):
        sale = make(site, owner)
        response = auth_client(cashier).post(url(sale), body(amount=0), format="json")
        assert response.status_code == 400
        assert response.json()["fieldErrors"]["amount"] == [
            "Le montant doit être supérieur à zéro."
        ]

    def test_overpayment_is_refused_with_the_balance_in_the_message(
        self, auth_client, cashier, site, owner
    ):
        """Cheaper to refuse than to explain a negative balance afterwards."""
        sale = make(site, owner)  # total 10 000
        auth_client(cashier).post(url(sale), body(amount=4_000), format="json")

        response = auth_client(cashier).post(url(sale), body(amount=6_001), format="json")

        assert response.status_code == 400
        assert response.json()["fieldErrors"]["amount"] == [
            "Le montant dépasse le solde restant dû (60,00 $US)."
        ]
        assert Payment.objects.count() == 1

    def test_paying_exactly_the_balance_is_allowed(
        self, auth_client, cashier, site, owner
    ):
        sale = make(site, owner)
        auth_client(cashier).post(url(sale), body(amount=4_000), format="json")
        response = auth_client(cashier).post(url(sale), body(amount=6_000), format="json")
        assert response.status_code == 201

    def test_a_payment_on_a_cancelled_sale_is_refused(
        self, auth_client, cashier, site, owner
    ):
        sale = make(site, owner)
        Sale.objects.filter(pk=sale.pk).update(status="CANCELLED")

        response = auth_client(cashier).post(url(sale), body(), format="json")

        assert response.status_code == 400
        assert response.json()["fieldErrors"]["amount"] == [
            "Cette vente est annulée : aucun paiement ne peut être ajouté."
        ]

    def test_an_invalid_method_is_rejected(self, auth_client, cashier, site, owner):
        sale = make(site, owner)
        response = auth_client(cashier).post(
            url(sale), body(method="BITCOIN"), format="json"
        )
        assert response.status_code == 400
        assert "method" in response.json()["fieldErrors"]

    def test_an_unknown_sale_is_404(self, auth_client, cashier, site):
        response = auth_client(cashier).post(
            f"/api/sales/{uuid.uuid4()}/payments/", body(), format="json"
        )
        assert response.status_code == 404
