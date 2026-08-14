"""POST /api/devices/register/ — called once per installation."""

import uuid

import pytest

from apps.accounts.models import Device

pytestmark = pytest.mark.django_db

URL = "/api/devices/register/"


def body(**overrides):
    payload = {"installId": str(uuid.uuid4()), "label": "Caisse principale"}
    payload.update(overrides)
    return payload


def test_first_registration_assigns_a_code(auth_client, cashier):
    response = auth_client(cashier).post(URL, body(), format="json")

    assert response.status_code == 201
    assert response.data["code"] == "C1"
    assert response.data["label"] == "Caisse principale"


def test_second_device_gets_the_next_code(auth_client, cashier):
    client = auth_client(cashier)
    client.post(URL, body(), format="json")

    response = client.post(URL, body(label="Caisse 2"), format="json")

    assert response.status_code == 201
    assert response.data["code"] == "C2"


def test_re_registration_returns_the_existing_code(auth_client, cashier):
    client = auth_client(cashier)
    install_id = str(uuid.uuid4())
    first = client.post(URL, body(installId=install_id), format="json")

    second = client.post(URL, body(installId=install_id), format="json")

    assert second.status_code == 200
    assert second.data["code"] == first.data["code"]
    assert Device.objects.count() == 1


def test_re_registration_updates_the_label(auth_client, cashier):
    client = auth_client(cashier)
    install_id = str(uuid.uuid4())
    client.post(URL, body(installId=install_id), format="json")

    response = client.post(
        URL, body(installId=install_id, label="Caisse du fond"), format="json"
    )

    assert response.data["label"] == "Caisse du fond"


def test_label_is_required(auth_client, cashier):
    response = auth_client(cashier).post(
        URL, {"installId": str(uuid.uuid4())}, format="json"
    )

    assert response.status_code == 400
    # The project's exception handler wraps DRF's dict in an envelope; the
    # per-field errors live under `field_errors`, which reaches the client as
    # `fieldErrors`.
    assert "label" in response.data["field_errors"]


def test_anonymous_is_refused(api_client):
    response = api_client.post(URL, body(), format="json")

    assert response.status_code == 401
