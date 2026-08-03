"""The settings singleton — no id in the path."""

import pytest

pytestmark = pytest.mark.django_db

URL = "/api/settings/"


def test_get_returns_the_site(auth_client, site, cashier):
    response = auth_client(cashier).get(URL)
    assert response.status_code == 200
    assert response.json() == {
        "id": str(site.id),
        "name": site.name,
        "address": site.address,
        "isDefault": True,
        "phone": site.phone,
        "email": site.email,
        "taxNumber": site.tax_number,
        "invoiceFooter": site.invoice_footer,
    }


def test_any_authenticated_role_may_read(auth_client, site, owner, manager, cashier):
    for user in (owner, manager, cashier):
        assert auth_client(user).get(URL).status_code == 200


def test_anonymous_may_not_read(api_client, site):
    assert api_client.get(URL).status_code == 401


def test_owner_may_update(auth_client, site, owner):
    response = auth_client(owner).patch(
        URL,
        {"name": "Alimentation Maisha SARL", "taxNumber": "B7654321A"},
        format="json",
    )
    assert response.status_code == 200
    assert response.json()["name"] == "Alimentation Maisha SARL"
    assert response.json()["taxNumber"] == "B7654321A"
    site.refresh_from_db()
    assert site.tax_number == "B7654321A"


@pytest.mark.parametrize("role", ["manager", "cashier"])
def test_non_owners_may_not_update(auth_client, site, request, role):
    user = request.getfixturevalue(role)
    response = auth_client(user).patch(URL, {"name": "Piraté"}, format="json")
    assert response.status_code == 403
    assert response.json()["code"] == "permission_denied"
    assert "propriétaire" in response.json()["message"].lower()


def test_blank_name_is_rejected(auth_client, site, owner):
    response = auth_client(owner).patch(URL, {"name": "   "}, format="json")
    assert response.status_code == 400
    assert "name" in response.json()["fieldErrors"]


def test_blank_address_is_rejected(auth_client, site, owner):
    response = auth_client(owner).patch(URL, {"address": ""}, format="json")
    assert response.status_code == 400
    assert "address" in response.json()["fieldErrors"]


def test_empty_optional_fields_become_null(auth_client, site, owner):
    """The frontend's type promises `string | null`, never `""`."""
    response = auth_client(owner).patch(
        URL, {"phone": "", "taxNumber": "", "invoiceFooter": ""}, format="json"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["phone"] is None
    assert body["taxNumber"] is None
    assert body["invoiceFooter"] is None


def test_explicit_nulls_are_accepted(auth_client, site, owner):
    response = auth_client(owner).patch(URL, {"phone": None}, format="json")
    assert response.status_code == 200
    assert response.json()["phone"] is None


def test_id_and_is_default_are_read_only(auth_client, site, owner):
    original = str(site.id)
    response = auth_client(owner).patch(
        URL, {"id": "00000000-0000-0000-0000-000000000000", "isDefault": False},
        format="json",
    )
    assert response.status_code == 200
    assert response.json()["id"] == original
    assert response.json()["isDefault"] is True
