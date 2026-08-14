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


def body(article, quantity=2, reference="FA-C2-2026-0007", sale_id=None):
    return {
        "id": str(sale_id or uuid.uuid4()),
        "customerId": None,
        "discount": 0,
        "discountRate": None,
        "note": None,
        "documentReference": reference,
        "lines": [
            {"articleId": str(article.id), "quantity": quantity, "unitPrice": 5_000}
        ],
    }


def headers(device):
    return {"HTTP_X_DEVICE_CODE": device.code}


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
    payload = body(article)

    first = client.post(URL, payload, format="json", **headers(device))
    second = client.post(URL, payload, format="json", **headers(device))

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.data["id"] == first.data["id"]
    assert Sale.objects.count() == 1


def test_replay_does_not_move_stock_twice(auth_client, cashier, site, device):
    article = stocked(site, quantity=10)
    client = auth_client(cashier)
    payload = body(article)

    client.post(URL, payload, format="json", **headers(device))
    client.post(URL, payload, format="json", **headers(device))

    assert StockLevel.objects.get(article=article, site=site).quantity == 8


def test_the_client_supplied_id_is_the_sale_pk(auth_client, cashier, site, device):
    article = stocked(site)
    sale_id = uuid.uuid4()

    response = auth_client(cashier).post(
        URL, body(article, sale_id=sale_id), format="json", **headers(device)
    )

    assert response.status_code == 201
    assert response.data["id"] == str(sale_id)


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
    """A different sale reusing a reference already taken is a client bug.
    A *replay* is the same id, and is handled above. `body()` mints a fresh
    id each call, which is what makes this a different sale."""
    article = stocked(site)
    client = auth_client(cashier)
    client.post(URL, body(article), format="json", **headers(device))

    response = client.post(URL, body(article), format="json", **headers(device))

    assert response.status_code == 400
    assert Sale.objects.count() == 1
