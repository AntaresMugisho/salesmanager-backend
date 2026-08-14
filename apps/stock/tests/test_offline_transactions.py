"""Stock transactions replayed from a device's offline queue."""

import uuid

import pytest

from apps.accounts.models import Device
from apps.catalogue.tests.factories import ArticleFactory
from apps.stock.models import StockLevel, StockTransaction
from apps.stock.tests.factories import StockLevelFactory

pytestmark = pytest.mark.django_db

URL = "/api/stock/transactions/"


@pytest.fixture
def device(db):
    return Device.objects.create(
        install_id=uuid.uuid4(), code="C2", label="Caisse principale"
    )


def stocked(site, quantity=100):
    article = ArticleFactory()
    StockLevelFactory(article=article, site=site, quantity=quantity)
    return article


def body(article, quantity=5, type="IN", reason="PURCHASE",
         reference="TR-C2-2026-0003", transaction_id=None):
    return {
        "id": str(transaction_id or uuid.uuid4()),
        "type": type,
        "reason": reason,
        "supplierId": None,
        # `reference` here is the supplier's delivery-note number, which is
        # what this endpoint has always meant by the word. The offline
        # document number is `documentReference`.
        "reference": None,
        "note": None,
        "documentReference": reference,
        "lines": [
            {"articleId": str(article.id), "quantity": quantity, "unitCost": 1_000}
        ],
    }


def headers(device):
    return {"HTTP_X_DEVICE_CODE": device.code}


def test_offline_transaction_keeps_its_reference(auth_client, manager, site, device):
    article = stocked(site)

    response = auth_client(manager).post(
        URL, body(article), format="json", **headers(device)
    )

    assert response.status_code == 201
    assert response.data["reference"] == "TR-C2-2026-0003"


def test_online_transaction_is_still_server_numbered(auth_client, manager, site):
    article = stocked(site)
    payload = body(article)
    del payload["documentReference"]

    response = auth_client(manager).post(URL, payload, format="json")

    assert response.status_code == 201
    assert "-C" not in response.data["reference"]


def test_replay_returns_the_same_transaction(auth_client, manager, site, device):
    article = stocked(site)
    client = auth_client(manager)
    payload = body(article)

    first = client.post(URL, payload, format="json", **headers(device))
    second = client.post(URL, payload, format="json", **headers(device))

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.data["id"] == first.data["id"]
    assert StockTransaction.objects.count() == 1


def test_replay_does_not_move_stock_twice(auth_client, manager, site, device):
    article = stocked(site, quantity=10)
    client = auth_client(manager)
    payload = body(article)

    client.post(URL, payload, format="json", **headers(device))
    client.post(URL, payload, format="json", **headers(device))

    assert StockLevel.objects.get(article=article, site=site).quantity == 15


def test_offline_out_transaction_may_go_negative(auth_client, manager, site, device):
    article = stocked(site, quantity=2)

    response = auth_client(manager).post(
        URL,
        body(article, quantity=5, type="OUT", reason="LOSS"),
        format="json",
        **headers(device),
    )

    assert response.status_code == 201
    assert StockLevel.objects.get(article=article, site=site).quantity == -3


def test_another_devices_reference_is_refused(auth_client, manager, site, device):
    article = stocked(site)

    response = auth_client(manager).post(
        URL,
        body(article, reference="TR-C9-2026-0003"),
        format="json",
        **headers(device),
    )

    assert response.status_code == 400
    assert StockTransaction.objects.count() == 0


def test_a_sale_reference_is_refused_on_a_transaction(
    auth_client, manager, site, device
):
    article = stocked(site)

    response = auth_client(manager).post(
        URL,
        body(article, reference="FA-C2-2026-0007"),
        format="json",
        **headers(device),
    )

    assert response.status_code == 400
    assert StockTransaction.objects.count() == 0


def test_duplicate_reference_is_refused(auth_client, manager, site, device):
    article = stocked(site)
    client = auth_client(manager)
    client.post(URL, body(article), format="json", **headers(device))

    response = client.post(URL, body(article), format="json", **headers(device))

    assert response.status_code == 400
    assert StockTransaction.objects.count() == 1


def test_the_client_supplied_id_is_the_transaction_pk(
    auth_client, manager, site, device
):
    article = stocked(site)
    transaction_id = uuid.uuid4()

    response = auth_client(manager).post(
        URL,
        body(article, transaction_id=transaction_id),
        format="json",
        **headers(device),
    )

    assert response.status_code == 201
    assert response.data["id"] == str(transaction_id)
