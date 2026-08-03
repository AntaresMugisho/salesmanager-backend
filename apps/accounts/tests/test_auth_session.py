import pytest

from apps.accounts.tests.factories import CashierFactory

pytestmark = pytest.mark.django_db

LOGIN = "/api/auth/login/"
REFRESH = "/api/auth/refresh/"
LOGOUT = "/api/auth/logout/"
ME = "/api/auth/me/"


@pytest.fixture
def session(api_client, site):
    CashierFactory(email="alice@shop.cd", password="motdepasse-de-test")
    response = api_client.post(
        LOGIN, {"email": "alice@shop.cd", "password": "motdepasse-de-test"},
        format="json",
    )
    return response.json()


def bearer(api_client, token):
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return api_client


# ---- refresh -------------------------------------------------------------


def test_refresh_returns_a_new_access_token(api_client, session):
    response = api_client.post(
        REFRESH, {"refreshToken": session["refreshToken"]}, format="json"
    )
    assert response.status_code == 200
    assert set(response.json()) == {"accessToken"}
    assert response.json()["accessToken"]


def test_refresh_rejects_a_garbage_token(api_client, session):
    """401, not 403.

    Without `RefreshView.get_authenticate_header`, DRF downgrades this to
    403 while the envelope still says `authentication_failed` — a
    contradiction that would send the frontend down its permission-denied
    path instead of back to the login screen.
    """
    response = api_client.post(REFRESH, {"refreshToken": "pas-un-jeton"}, format="json")
    assert response.status_code == 401
    assert response.json()["code"] == "authentication_failed"


def test_refresh_requires_the_field(api_client, session):
    response = api_client.post(REFRESH, {}, format="json")
    assert response.status_code == 400
    assert "refreshToken" in response.json()["fieldErrors"]


# ---- logout --------------------------------------------------------------


def test_logout_blacklists_the_refresh_token(api_client, session):
    client = bearer(api_client, session["accessToken"])
    assert (
        client.post(LOGOUT, {"refreshToken": session["refreshToken"]}, format="json").status_code
        == 204
    )

    client.credentials()
    response = client.post(
        REFRESH, {"refreshToken": session["refreshToken"]}, format="json"
    )
    assert response.status_code == 401


def test_logout_is_idempotent(api_client, session):
    client = bearer(api_client, session["accessToken"])
    payload = {"refreshToken": session["refreshToken"]}
    assert client.post(LOGOUT, payload, format="json").status_code == 204
    assert client.post(LOGOUT, payload, format="json").status_code == 204


def test_logout_tolerates_a_garbage_token(api_client, session):
    """The client's only sensible reaction either way is to drop its
    session, so a bad token is not worth an error."""
    client = bearer(api_client, session["accessToken"])
    response = client.post(LOGOUT, {"refreshToken": "pas-un-jeton"}, format="json")
    assert response.status_code == 204


def test_logout_requires_authentication(api_client, session):
    response = api_client.post(
        LOGOUT, {"refreshToken": session["refreshToken"]}, format="json"
    )
    assert response.status_code == 401


# ---- me ------------------------------------------------------------------


def test_me_returns_the_current_user(api_client, session):
    client = bearer(api_client, session["accessToken"])
    response = client.get(ME)
    assert response.status_code == 200
    assert response.json() == session["user"]


def test_me_rejects_anonymous_callers(api_client, site):
    response = api_client.get(ME)
    assert response.status_code == 401
    assert response.json()["code"] == "authentication_failed"


def test_me_rejects_a_session_cookie(client, site):
    """JWT only — a stale admin cookie must never authenticate an API call."""
    user = CashierFactory(email="alice@shop.cd", password="motdepasse-de-test")
    client.force_login(user)
    assert client.get(ME).status_code == 401
