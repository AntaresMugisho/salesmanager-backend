"""Single movements replayed from a device's offline queue."""

import uuid

import pytest

from apps.accounts.models import Device
from apps.catalogue.tests.factories import ArticleFactory
from apps.stock.models import StockLevel, StockMovement
from apps.stock.tests.factories import StockLevelFactory

pytestmark = pytest.mark.django_db

URL = "/api/stock/movements/"


@pytest.fixture
def device(db):
    return Device.objects.create(
        install_id=uuid.uuid4(), code="C2", label="Caisse principale"
    )


def stocked(site, quantity=100):
    article = ArticleFactory()
    StockLevelFactory(article=article, site=site, quantity=quantity)
    return article


def body(article, quantity=5, type="IN", reason="PURCHASE", movement_id=None):
    return {
        "id": str(movement_id or uuid.uuid4()),
        "articleId": str(article.id),
        "type": type,
        "reason": reason,
        "quantity": quantity,
        "unitCost": None,
        "reference": None,
        "note": None,
    }


def headers(device):
    return {"HTTP_X_DEVICE_CODE": device.code}


def test_the_client_supplied_id_is_the_movement_pk(
    auth_client, manager, site, device
):
    article = stocked(site)
    movement_id = uuid.uuid4()

    response = auth_client(manager).post(
        URL, body(article, movement_id=movement_id), format="json", **headers(device)
    )

    assert response.status_code == 201
    assert response.data["id"] == str(movement_id)


def test_replaying_does_not_move_stock_twice(auth_client, manager, site, device):
    article = stocked(site, quantity=10)
    client = auth_client(manager)
    payload = body(article, quantity=5)

    first = client.post(URL, payload, format="json", **headers(device))
    second = client.post(URL, payload, format="json", **headers(device))

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.data["id"] == first.data["id"]
    assert StockLevel.objects.get(article=article, site=site).quantity == 15
    assert StockMovement.objects.filter(article=article).count() == 1


def test_an_offline_out_may_go_negative(auth_client, manager, site, device):
    article = stocked(site, quantity=2)

    response = auth_client(manager).post(
        URL,
        body(article, quantity=5, type="OUT", reason="LOSS"),
        format="json",
        **headers(device),
    )

    assert response.status_code == 201
    assert StockLevel.objects.get(article=article, site=site).quantity == -3


def test_an_online_out_may_not_go_negative(auth_client, manager, site):
    article = stocked(site, quantity=2)
    payload = body(article, quantity=5, type="OUT", reason="LOSS")

    response = auth_client(manager).post(URL, payload, format="json")

    assert response.status_code == 400
    assert StockLevel.objects.get(article=article, site=site).quantity == 2


def test_a_movement_without_an_id_still_works(auth_client, manager, site):
    """The online path sends no id and must be unaffected."""
    article = stocked(site, quantity=10)
    payload = body(article, quantity=5)
    del payload["id"]

    response = auth_client(manager).post(URL, payload, format="json")

    assert response.status_code == 201
    assert StockLevel.objects.get(article=article, site=site).quantity == 15


def test_a_replayed_adjustment_sets_the_level_to_the_count(
    auth_client, manager, site, device
):
    """The count wins: `quantity` is the counted target, not a delta, and the
    server applies it to whatever level it currently holds."""
    article = stocked(site, quantity=12)

    response = auth_client(manager).post(
        URL,
        body(article, quantity=7, type="ADJUSTMENT", reason="COUNT_CORRECTION"),
        format="json",
        **headers(device),
    )

    assert response.status_code == 201
    assert StockLevel.objects.get(article=article, site=site).quantity == 7
