"""Customer endpoints. Payload from the frontend's `Customer` type."""

import pytest

from apps.sales.models import Customer
from apps.sales.tests.factories import CustomerFactory, SaleFactory

pytestmark = pytest.mark.django_db

LIST_URL = "/api/customers/"


def detail_url(customer) -> str:
    return f"{LIST_URL}{customer.id}/"


class TestRead:
    def test_the_payload_matches_the_frontend_type(self, auth_client, cashier):
        CustomerFactory(name="Kivu Market")
        response = auth_client(cashier).get(LIST_URL)

        assert response.status_code == 200
        assert set(response.json()["results"][0]) == {
            "id",
            "name",
            "contactName",
            "email",
            "phone",
            "address",
            "taxNumber",
            "notes",
            "isActive",
            "createdAt",
        }

    def test_empty_optionals_serialise_as_null(self, auth_client, cashier):
        CustomerFactory(contact_name=None, email=None, phone=None, tax_number=None)
        row = auth_client(cashier).get(LIST_URL).json()["results"][0]
        assert row["contactName"] is None
        assert row["taxNumber"] is None

    def test_ordered_by_name(self, auth_client, cashier):
        CustomerFactory(name="Zeta")
        CustomerFactory(name="Alpha")
        response = auth_client(cashier).get(LIST_URL)
        assert [r["name"] for r in response.json()["results"]] == ["Alpha", "Zeta"]

    def test_search_covers_name_contact_email_and_phone(self, auth_client, cashier):
        CustomerFactory(
            name="Kivu Market",
            contact_name="Marie",
            email="marie@kivu.cd",
            phone="0990111222",
        )
        CustomerFactory(
            name="Goma Store",
            contact_name="Paul",
            email="paul@goma.cd",
            phone="0821333444",
        )
        client = auth_client(cashier)

        assert client.get(f"{LIST_URL}?search=kivu").json()["count"] == 1
        assert client.get(f"{LIST_URL}?search=paul").json()["count"] == 1
        assert client.get(f"{LIST_URL}?search=marie@kivu").json()["count"] == 1
        assert client.get(f"{LIST_URL}?search=0821").json()["count"] == 1

    def test_a_cashier_may_read(self, auth_client, cashier):
        CustomerFactory()
        assert auth_client(cashier).get(LIST_URL).status_code == 200


class TestWrite:
    def test_a_manager_can_create(self, auth_client, manager):
        response = auth_client(manager).post(
            LIST_URL,
            {
                "name": "Kivu Market",
                "contactName": "Marie Kabeya",
                "email": "marie@kivu.cd",
                "phone": "+243 990 111 222",
                "address": "10 avenue du Lac",
                "taxNumber": "A1234567B",
                "notes": "",
                "isActive": True,
            },
            format="json",
        )
        assert response.status_code == 201
        assert response.json()["taxNumber"] == "A1234567B"
        assert response.json()["notes"] is None

    def test_a_duplicate_name_is_rejected_case_insensitively(
        self, auth_client, manager
    ):
        CustomerFactory(name="Kivu Market")
        response = auth_client(manager).post(
            LIST_URL, {"name": "KIVU MARKET", "isActive": True}, format="json"
        )
        assert response.status_code == 400
        assert response.json()["fieldErrors"]["name"] == ["Un client porte déjà ce nom."]

    def test_an_invalid_phone_is_rejected(self, auth_client, manager):
        response = auth_client(manager).post(
            LIST_URL,
            {"name": "Kivu Market", "phone": "pas-un-numéro!!", "isActive": True},
            format="json",
        )
        assert response.status_code == 400
        assert "phone" in response.json()["fieldErrors"]

    def test_an_over_long_tax_number_is_rejected(self, auth_client, manager):
        response = auth_client(manager).post(
            LIST_URL,
            {"name": "Kivu Market", "taxNumber": "X" * 31, "isActive": True},
            format="json",
        )
        assert response.status_code == 400
        assert "taxNumber" in response.json()["fieldErrors"]

    def test_a_customer_can_be_archived(self, auth_client, manager):
        customer = CustomerFactory(is_active=True)
        response = auth_client(manager).patch(
            detail_url(customer), {"isActive": False}, format="json"
        )
        assert response.status_code == 200
        customer.refresh_from_db()
        assert customer.is_active is False


class TestDelete:
    def test_an_owner_can_delete_an_unused_customer(self, auth_client, owner):
        customer = CustomerFactory()
        assert auth_client(owner).delete(detail_url(customer)).status_code == 204
        assert Customer.objects.count() == 0

    def test_a_customer_with_sales_is_409(self, auth_client, owner, site):
        customer = CustomerFactory()
        SaleFactory(customer=customer, user=owner, site=site)
        SaleFactory(customer=customer, user=owner, site=site)

        response = auth_client(owner).delete(detail_url(customer))

        assert response.status_code == 409
        assert response.json()["code"] == "conflict"
        assert response.json()["message"] == (
            "Ce client est lié à 2 ventes et ne peut pas être supprimé. "
            "Archivez-le à la place."
        )

    def test_the_message_is_singular_for_one_sale(self, auth_client, owner, site):
        customer = CustomerFactory()
        SaleFactory(customer=customer, user=owner, site=site)
        response = auth_client(owner).delete(detail_url(customer))
        assert response.json()["message"] == (
            "Ce client est lié à 1 vente et ne peut pas être supprimé. "
            "Archivez-le à la place."
        )


class TestPermissions:
    @pytest.mark.parametrize("method", ["post", "patch", "delete"])
    def test_a_cashier_may_not_write(self, auth_client, cashier, method):
        customer = CustomerFactory()
        client = auth_client(cashier)
        url = LIST_URL if method == "post" else detail_url(customer)
        response = getattr(client, method)(url, {"name": "X"}, format="json")
        assert response.status_code == 403

    def test_a_manager_may_not_delete(self, auth_client, manager):
        customer = CustomerFactory()
        assert auth_client(manager).delete(detail_url(customer)).status_code == 403
