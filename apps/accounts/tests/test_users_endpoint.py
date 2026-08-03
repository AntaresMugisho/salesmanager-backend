"""Owner-only user management, plus the last-owner guard.

Without that guard a single misclick locks every owner-only endpoint —
including the one that would undo it.
"""

import pytest

from apps.accounts.models import User
from apps.accounts.tests.factories import CashierFactory, ManagerFactory, OwnerFactory

pytestmark = pytest.mark.django_db

URL = "/api/users/"


# ---- permissions ---------------------------------------------------------


@pytest.mark.parametrize("role", ["manager", "cashier"])
def test_non_owners_are_refused(auth_client, site, request, role):
    user = request.getfixturevalue(role)
    assert auth_client(user).get(URL).status_code == 403


def test_anonymous_is_refused(api_client, site):
    assert api_client.get(URL).status_code == 401


# ---- list ----------------------------------------------------------------


def test_list_is_paginated(auth_client, site, owner):
    CashierFactory.create_batch(3)
    body = auth_client(owner).get(URL).json()
    assert set(body) == {"count", "next", "previous", "results"}
    assert body["count"] == 4


def test_list_rows_are_camel_case(auth_client, site, owner):
    row = auth_client(owner).get(URL).json()["results"][0]
    assert set(row) == {"id", "fullName", "email", "avatarUrl", "role"}


def test_list_honours_camel_case_page_size(auth_client, site, owner):
    CashierFactory.create_batch(5)
    body = auth_client(owner).get(f"{URL}?pageSize=2").json()
    assert len(body["results"]) == 2
    assert body["count"] == 6


def test_list_honours_camel_case_ordering(auth_client, site, owner):
    """End-to-end proof that ordering *values* are translated."""
    CashierFactory(full_name="Zoé Amani")
    CashierFactory(full_name="Aline Byamungu")
    names = [
        row["fullName"]
        for row in auth_client(owner).get(f"{URL}?ordering=-fullName").json()["results"]
    ]
    assert names == sorted(names, reverse=True)


def test_list_supports_search(auth_client, site, owner):
    CashierFactory(full_name="Zoé Amani")
    results = auth_client(owner).get(f"{URL}?search=Amani").json()["results"]
    assert [row["fullName"] for row in results] == ["Zoé Amani"]


# ---- create --------------------------------------------------------------


def test_owner_creates_a_user(auth_client, site, owner):
    response = auth_client(owner).post(
        URL,
        {
            "email": "nouveau@shop.cd",
            "fullName": "Nouveau Caissier",
            "password": "un-mot-de-passe-solide",
            "role": "CASHIER",
        },
        format="json",
    )
    assert response.status_code == 201
    assert response.json()["email"] == "nouveau@shop.cd"
    assert "password" not in response.json()
    assert User.objects.get(email="nouveau@shop.cd").check_password(
        "un-mot-de-passe-solide"
    )


def test_duplicate_email_differing_only_in_case_is_rejected(auth_client, site, owner):
    CashierFactory(email="alice@shop.cd")
    response = auth_client(owner).post(
        URL,
        {
            "email": "ALICE@SHOP.CD",
            "fullName": "Alice Bis",
            "password": "un-mot-de-passe-solide",
            "role": "CASHIER",
        },
        format="json",
    )
    assert response.status_code == 400
    assert "email" in response.json()["fieldErrors"]


def test_weak_password_is_rejected(auth_client, site, owner):
    response = auth_client(owner).post(
        URL,
        {
            "email": "nouveau@shop.cd",
            "fullName": "Nouveau Caissier",
            "password": "1234",
            "role": "CASHIER",
        },
        format="json",
    )
    assert response.status_code == 400
    assert "password" in response.json()["fieldErrors"]


def test_unknown_role_is_rejected(auth_client, site, owner):
    response = auth_client(owner).post(
        URL,
        {
            "email": "nouveau@shop.cd",
            "fullName": "Nouveau",
            "password": "un-mot-de-passe-solide",
            "role": "ADMIN",
        },
        format="json",
    )
    assert response.status_code == 400
    assert "role" in response.json()["fieldErrors"]


# ---- update --------------------------------------------------------------


def test_owner_updates_a_role(auth_client, site, owner):
    target = CashierFactory()
    response = auth_client(owner).patch(
        f"{URL}{target.id}/", {"role": "MANAGER"}, format="json"
    )
    assert response.status_code == 200
    target.refresh_from_db()
    assert target.role == User.Role.MANAGER


def test_owner_changes_a_password(auth_client, site, owner):
    target = CashierFactory()
    response = auth_client(owner).patch(
        f"{URL}{target.id}/", {"password": "un-autre-mot-de-passe"}, format="json"
    )
    assert response.status_code == 200
    target.refresh_from_db()
    assert target.check_password("un-autre-mot-de-passe")


# ---- delete --------------------------------------------------------------


def test_delete_deactivates_rather_than_destroys(auth_client, site, owner):
    """Movements and sales stamp userName; the row must survive."""
    target = CashierFactory()
    assert auth_client(owner).delete(f"{URL}{target.id}/").status_code == 204
    target.refresh_from_db()
    assert target.is_active is False
    assert User.objects.filter(pk=target.pk).exists()


# ---- last-owner guard ----------------------------------------------------


def test_the_last_owner_cannot_be_deleted(auth_client, site, owner):
    response = auth_client(owner).delete(f"{URL}{owner.id}/")
    assert response.status_code == 409
    assert response.json()["code"] == "conflict"
    owner.refresh_from_db()
    assert owner.is_active is True


def test_the_last_owner_cannot_be_demoted(auth_client, site, owner):
    response = auth_client(owner).patch(
        f"{URL}{owner.id}/", {"role": "MANAGER"}, format="json"
    )
    assert response.status_code == 409
    owner.refresh_from_db()
    assert owner.role == User.Role.OWNER


def test_the_last_owner_cannot_be_deactivated(auth_client, site, owner):
    response = auth_client(owner).patch(
        f"{URL}{owner.id}/", {"isActive": False}, format="json"
    )
    assert response.status_code == 409
    owner.refresh_from_db()
    assert owner.is_active is True


def test_an_owner_may_be_demoted_when_another_active_owner_remains(
    auth_client, site, owner
):
    other = OwnerFactory()
    response = auth_client(owner).patch(
        f"{URL}{other.id}/", {"role": "MANAGER"}, format="json"
    )
    assert response.status_code == 200


def test_an_inactive_owner_does_not_count_towards_the_guard(auth_client, site, owner):
    OwnerFactory(is_active=False)
    assert auth_client(owner).delete(f"{URL}{owner.id}/").status_code == 409


def test_a_manager_is_not_protected_by_the_guard(auth_client, site, owner):
    target = ManagerFactory()
    assert auth_client(owner).delete(f"{URL}{target.id}/").status_code == 204
