"""Sales replayed from a device's offline queue."""

import uuid

import pytest

from apps.accounts.models import Device
from apps.catalogue.tests.factories import ArticleFactory
from apps.sales.models import Sale
from apps.stock.models import StockLevel
from apps.stock.tests.factories import StockLevelFactory

pytestmark = pytest.mark.django_db

URL = "/api/sales/"


@pytest.fixture
def device(db):
    return Device.objects.create(
        install_id=uuid.uuid4(), code="C2", label="Caisse principale"
    )


def stocked(site, quantity=100):
    article = ArticleFactory()
    StockLevelFactory(article=article, site=site, quantity=quantity)
    return article


def body(article, quantity=2, reference="FA-C2-2026-0007"):
    return {
        "customerId": None,
        "discount": 0,
        "discountRate": None,
        "note": None,
        "documentReference": reference,
        "lines": [
            {"articleId": str(article.id), "quantity": quantity, "unitPrice": 5_000}
        ],
    }


def headers(device, key=None):
    return {
        "HTTP_X_DEVICE_CODE": device.code,
        "HTTP_IDEMPOTENCY_KEY": str(key or uuid.uuid4()),
    }


def test_offline_sale_keeps_the_reference_it_arrived_with(
    auth_client, cashier, site, device
):
    article = stocked(site)

    response = auth_client(cashier).post(
        URL, body(article), format="json", **headers(device)
    )

    assert response.status_code == 201
    assert response.data["reference"] == "FA-C2-2026-0007"


def test_online_sale_is_still_server_numbered(auth_client, cashier, site):
    article = stocked(site)
    payload = body(article)
    del payload["documentReference"]

    response = auth_client(cashier).post(URL, payload, format="json")

    assert response.status_code == 201
    assert response.data["reference"].startswith("FA-2")
    assert "-C" not in response.data["reference"]


def test_replay_returns_the_same_sale_without_creating_a_second(
    auth_client, cashier, site, device
):
    article = stocked(site)
    client = auth_client(cashier)
    key = uuid.uuid4()

    first = client.post(URL, body(article), format="json", **headers(device, key))
    second = client.post(URL, body(article), format="json", **headers(device, key))

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.data["id"] == first.data["id"]
    assert Sale.objects.count() == 1


def test_replay_does_not_move_stock_twice(auth_client, cashier, site, device):
    article = stocked(site, quantity=10)
    client = auth_client(cashier)
    key = uuid.uuid4()

    client.post(URL, body(article), format="json", **headers(device, key))
    client.post(URL, body(article), format="json", **headers(device, key))

    assert StockLevel.objects.get(article=article, site=site).quantity == 8


def test_offline_sale_may_oversell(auth_client, cashier, site, device):
    article = stocked(site, quantity=1)

    response = auth_client(cashier).post(
        URL, body(article, quantity=3), format="json", **headers(device)
    )

    assert response.status_code == 201
    assert StockLevel.objects.get(article=article, site=site).quantity == -2


def test_online_sale_may_not_oversell(auth_client, cashier, site):
    article = stocked(site, quantity=1)
    payload = body(article, quantity=3)
    del payload["documentReference"]

    response = auth_client(cashier).post(URL, payload, format="json")

    assert response.status_code == 400
    assert StockLevel.objects.get(article=article, site=site).quantity == 1


def test_another_devices_reference_is_refused(auth_client, cashier, site, device):
    article = stocked(site)

    response = auth_client(cashier).post(
        URL,
        body(article, reference="FA-C9-2026-0007"),
        format="json",
        **headers(device),
    )

    assert response.status_code == 400
    assert Sale.objects.count() == 0


def test_unknown_device_code_is_refused(auth_client, cashier, site, device):
    article = stocked(site)

    response = auth_client(cashier).post(
        URL,
        body(article),
        format="json",
        HTTP_X_DEVICE_CODE="C99",
        HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
    )

    assert response.status_code == 400
    assert Sale.objects.count() == 0


def test_reference_without_a_device_header_is_refused(auth_client, cashier, site):
    article = stocked(site)

    response = auth_client(cashier).post(URL, body(article), format="json")

    assert response.status_code == 400
    assert Sale.objects.count() == 0


def test_duplicate_reference_is_refused(auth_client, cashier, site, device):
    """A *fresh* idempotency key with a reference already used is a client
    bug, and must read as one. `headers()` mints a new key each call, which is
    what makes this a different request rather than the replay above."""
    article = stocked(site)
    client = auth_client(cashier)
    client.post(URL, body(article), format="json", **headers(device))

    response = client.post(URL, body(article), format="json", **headers(device))

    assert response.status_code == 400
    assert Sale.objects.count() == 1
