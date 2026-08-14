"""Payments replayed from a device's offline queue.

`POST /sales/{id}/payments/` had no idempotency at all before this: a sync
that died between the sale POST and the payment POST would take the money
twice on retry.
"""

import uuid

import pytest

from apps.catalogue.tests.factories import ArticleFactory
from apps.sales.models import Payment
from apps.sales.services import create_sale
from apps.stock.tests.factories import StockLevelFactory

pytestmark = pytest.mark.django_db


def sale_with_stock(site, user, quantity=2, unit_price=5_000):
    article = ArticleFactory()
    StockLevelFactory(article=article, site=site, quantity=100)
    return create_sale(
        lines=[
            {"article": article, "quantity": quantity, "unit_price": unit_price}
        ],
        user=user,
        site=site,
    )


def body(amount=10_000, payment_id=None):
    return {
        "id": str(payment_id or uuid.uuid4()),
        "amount": amount,
        "method": "CASH",
        "paidAt": "2026-08-14",
        "reference": None,
        "note": None,
    }


def url(sale):
    return f"/api/sales/{sale.id}/payments/"


def test_a_payment_keeps_its_client_minted_id(auth_client, cashier, site):
    sale = sale_with_stock(site, cashier)
    payment_id = uuid.uuid4()

    response = auth_client(cashier).post(
        url(sale), body(payment_id=payment_id), format="json"
    )

    assert response.status_code == 201
    assert response.data["id"] == str(payment_id)


def test_replaying_a_payment_does_not_pay_twice(auth_client, cashier, site):
    sale = sale_with_stock(site, cashier)
    client = auth_client(cashier)
    payload = body()

    first = client.post(url(sale), payload, format="json")
    second = client.post(url(sale), payload, format="json")

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.data["id"] == first.data["id"]
    assert Payment.objects.filter(sale=sale).count() == 1


def test_a_payment_without_an_id_still_works(auth_client, cashier, site):
    """The online path sends no id and must be unaffected."""
    sale = sale_with_stock(site, cashier)
    payload = body()
    del payload["id"]

    response = auth_client(cashier).post(url(sale), payload, format="json")

    assert response.status_code == 201
    assert Payment.objects.filter(sale=sale).count() == 1


def test_an_id_belonging_to_another_sale_is_refused(auth_client, cashier, site):
    """Looking up by pk alone would hand back a different sale's payment."""
    first_sale = sale_with_stock(site, cashier)
    second_sale = sale_with_stock(site, cashier)
    client = auth_client(cashier)
    payload = body(amount=4_000)

    client.post(url(first_sale), payload, format="json")
    response = client.post(url(second_sale), payload, format="json")

    assert response.status_code == 400
    assert Payment.objects.filter(sale=second_sale).count() == 0


def test_two_distinct_payments_both_land(auth_client, cashier, site):
    sale = sale_with_stock(site, cashier)
    client = auth_client(cashier)

    client.post(url(sale), body(amount=4_000), format="json")
    client.post(url(sale), body(amount=6_000), format="json")

    assert Payment.objects.filter(sale=sale).count() == 2
