"""Login.

Unknown email, wrong password and inactive account must be
indistinguishable: anything else lets an unauthenticated caller enumerate
accounts.
"""

import pytest

from apps.accounts.tests.factories import CashierFactory

pytestmark = pytest.mark.django_db

URL = "/api/auth/login/"


def test_login_returns_the_session(api_client, site):
    user = CashierFactory(email="alice@shop.cd", password="motdepasse-de-test")

    response = api_client.post(
        URL, {"email": "alice@shop.cd", "password": "motdepasse-de-test"}, format="json"
    )

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"user", "siteId", "accessToken", "refreshToken"}
    assert body["siteId"] == str(site.id)
    assert body["accessToken"]
    assert body["refreshToken"]
    assert body["user"] == {
        "id": str(user.id),
        "fullName": user.full_name,
        "email": "alice@shop.cd",
        "avatarUrl": None,
        "role": "CASHIER",
    }


def test_the_payload_is_camel_case(api_client, site):
    CashierFactory(email="alice@shop.cd", password="motdepasse-de-test")
    response = api_client.post(
        URL, {"email": "alice@shop.cd", "password": "motdepasse-de-test"}, format="json"
    )
    body = response.json()
    assert "site_id" not in body
    assert "full_name" not in body["user"]


def test_login_is_case_insensitive_on_email(api_client, site):
    CashierFactory(email="alice@shop.cd", password="motdepasse-de-test")
    response = api_client.post(
        URL, {"email": "ALICE@SHOP.CD", "password": "motdepasse-de-test"}, format="json"
    )
    assert response.status_code == 200


@pytest.mark.parametrize(
    "credentials",
    [
        {"email": "inconnu@shop.cd", "password": "motdepasse-de-test"},
        {"email": "alice@shop.cd", "password": "mauvais-mot-de-passe"},
    ],
    ids=["unknown-email", "wrong-password"],
)
def test_failures_are_indistinguishable(api_client, site, credentials):
    CashierFactory(email="alice@shop.cd", password="motdepasse-de-test")
    response = api_client.post(URL, credentials, format="json")

    assert response.status_code == 400
    assert response.json() == {
        "code": "invalid_credentials",
        "message": "Identifiants invalides.",
        "fieldErrors": {
            "email": ["Aucun compte ne correspond à ces identifiants."]
        },
    }


def test_inactive_account_gets_the_same_response(api_client, site):
    CashierFactory(
        email="alice@shop.cd", password="motdepasse-de-test", is_active=False
    )
    response = api_client.post(
        URL, {"email": "alice@shop.cd", "password": "motdepasse-de-test"}, format="json"
    )
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_credentials"


def test_missing_fields_are_a_validation_error(api_client, site):
    response = api_client.post(URL, {}, format="json")
    assert response.status_code == 400
    body = response.json()
    assert body["code"] == "validation_error"
    assert set(body["fieldErrors"]) == {"email", "password"}


def test_login_needs_no_token(api_client, site):
    """The endpoint must be reachable without credentials.

    Asserting the exact status, not merely `!= 401`: a 404 would satisfy the
    looser assertion, so the test would have passed before the endpoint
    existed.
    """
    response = api_client.post(URL, {}, format="json")
    assert response.status_code == 400


def test_login_ignores_a_malformed_authorization_header(api_client, site):
    """`authentication_classes = []` is what makes this pass: otherwise DRF
    would reject the header before the view ran."""
    CashierFactory(email="alice@shop.cd", password="motdepasse-de-test")
    api_client.credentials(HTTP_AUTHORIZATION="Bearer pas-un-jeton")
    response = api_client.post(
        URL, {"email": "alice@shop.cd", "password": "motdepasse-de-test"}, format="json"
    )
    assert response.status_code == 200


def test_inactive_account_still_hashes_the_password(api_client, site):
    """Regression for the timing side-channel: `or` short-circuits, so
    `not user.is_active or not user.check_password(...)` would skip the
    hash entirely for a deactivated account, answering ~1e6x faster than a
    wrong password and enumerating every deactivated account. Assert the
    call count rather than timing, which would be flaky.
    """
    from unittest.mock import patch

    from apps.accounts.models import User

    CashierFactory(
        email="alice@shop.cd", password="motdepasse-de-test", is_active=False
    )
    with patch.object(User, "check_password", return_value=False) as mocked:
        response = api_client.post(
            URL,
            {"email": "alice@shop.cd", "password": "motdepasse-de-test"},
            format="json",
        )
    assert response.status_code == 400
    mocked.assert_called_once()


def test_login_reports_an_unconfigured_deployment(api_client):
    """No Site row: actionable 409 rather than an opaque 500."""
    CashierFactory(email="alice@shop.cd", password="motdepasse-de-test")
    response = api_client.post(
        URL, {"email": "alice@shop.cd", "password": "motdepasse-de-test"}, format="json"
    )
    assert response.status_code == 409
    assert response.json()["code"] == "conflict"
    assert "bootstrap" in response.json()["message"]
