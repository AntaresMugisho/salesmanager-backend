"""Supplier endpoints. Payload from the frontend's `Supplier` type."""

import pytest

from apps.catalogue.models import Supplier
from apps.catalogue.tests.factories import ArticleFactory, SupplierFactory

pytestmark = pytest.mark.django_db

LIST_URL = "/api/suppliers/"


def detail_url(supplier) -> str:
    return f"{LIST_URL}{supplier.id}/"


class TestRead:
    def test_the_payload_matches_the_frontend_type(self, auth_client, cashier):
        SupplierFactory(name="Brasimba")
        response = auth_client(cashier).get(LIST_URL)

        assert response.status_code == 200
        assert set(response.json()["results"][0]) == {
            "id",
            "name",
            "contactName",
            "email",
            "phone",
            "address",
            "notes",
            "isActive",
            "createdAt",
        }

    def test_empty_optionals_serialise_as_null(self, auth_client, cashier):
        SupplierFactory(contact_name=None, email=None, phone=None, address=None)
        row = auth_client(cashier).get(LIST_URL).json()["results"][0]
        assert row["contactName"] is None
        assert row["email"] is None
        assert row["phone"] is None
        assert row["address"] is None

    def test_ordered_by_name(self, auth_client, cashier):
        SupplierFactory(name="Zeta")
        SupplierFactory(name="Alpha")
        response = auth_client(cashier).get(LIST_URL)
        assert [r["name"] for r in response.json()["results"]] == ["Alpha", "Zeta"]

    def test_search_covers_name_contact_email_and_phone(self, auth_client, cashier):
        SupplierFactory(
            name="Brasimba",
            contact_name="Jean",
            email="jean@bra.cd",
            phone="0990111222",
        )
        SupplierFactory(
            name="Bralima",
            contact_name="Marie",
            email="marie@bra.cd",
            phone="0821333444",
        )
        client = auth_client(cashier)

        assert client.get(f"{LIST_URL}?search=brasimba").json()["count"] == 1
        assert client.get(f"{LIST_URL}?search=marie").json()["count"] == 1
        assert client.get(f"{LIST_URL}?search=jean@bra").json()["count"] == 1
        assert client.get(f"{LIST_URL}?search=0821").json()["count"] == 1


class TestWrite:
    def test_a_manager_can_create(self, auth_client, manager):
        response = auth_client(manager).post(
            LIST_URL,
            {
                "name": "Brasimba",
                "contactName": "Jean Kabila",
                "email": "jean@brasimba.cd",
                "phone": "+243 990 111 222",
                "address": "18 avenue du Lac",
                "notes": "",
                "isActive": True,
            },
            format="json",
        )
        assert response.status_code == 201
        assert response.json()["contactName"] == "Jean Kabila"
        assert response.json()["notes"] is None

    def test_a_duplicate_name_is_rejected_case_insensitively(
        self, auth_client, manager
    ):
        SupplierFactory(name="Brasimba")
        response = auth_client(manager).post(
            LIST_URL, {"name": "BRASIMBA", "isActive": True}, format="json"
        )
        assert response.status_code == 400
        assert response.json()["fieldErrors"]["name"] == [
            "Un fournisseur porte déjà ce nom."
        ]

    def test_an_invalid_phone_is_rejected(self, auth_client, manager):
        response = auth_client(manager).post(
            LIST_URL,
            {"name": "Brasimba", "phone": "pas-un-numéro!!", "isActive": True},
            format="json",
        )
        assert response.status_code == 400
        assert "phone" in response.json()["fieldErrors"]

    def test_an_invalid_email_is_rejected(self, auth_client, manager):
        response = auth_client(manager).post(
            LIST_URL,
            {"name": "Brasimba", "email": "pas-une-adresse", "isActive": True},
            format="json",
        )
        assert response.status_code == 400
        assert "email" in response.json()["fieldErrors"]

    def test_a_supplier_can_be_deactivated(self, auth_client, manager):
        supplier = SupplierFactory(is_active=True)
        response = auth_client(manager).patch(
            detail_url(supplier), {"isActive": False}, format="json"
        )
        assert response.status_code == 200
        supplier.refresh_from_db()
        assert supplier.is_active is False


class TestDelete:
    def test_an_owner_can_delete_an_unused_supplier(self, auth_client, owner):
        supplier = SupplierFactory()
        assert auth_client(owner).delete(detail_url(supplier)).status_code == 204
        assert Supplier.objects.count() == 0

    def test_a_supplier_with_articles_is_409(self, auth_client, owner):
        supplier = SupplierFactory()
        ArticleFactory(supplier=supplier)
        ArticleFactory(supplier=supplier)

        response = auth_client(owner).delete(detail_url(supplier))

        assert response.status_code == 409
        assert response.json()["code"] == "conflict"
        assert response.json()["message"] == (
            "Ce fournisseur est lié à 2 articles et ne peut pas être supprimé."
        )

    def test_the_message_is_singular_for_one_article(self, auth_client, owner):
        supplier = SupplierFactory()
        ArticleFactory(supplier=supplier)
        response = auth_client(owner).delete(detail_url(supplier))
        assert response.json()["message"] == (
            "Ce fournisseur est lié à 1 article et ne peut pas être supprimé."
        )


    def test_a_supplier_with_transactions_is_409_not_500(
        self, auth_client, owner, site
    ):
        """StockTransaction.supplier is PROTECT. Without an explicit guard
        this surfaces as an unhandled ProtectedError."""
        from apps.stock.services import create_transaction

        supplier = SupplierFactory()
        create_transaction(
            type="IN",
            reason="PURCHASE",
            lines=[{"article": ArticleFactory(), "quantity": 1, "unit_cost": None}],
            user=owner,
            site=site,
            supplier=supplier,
        )

        response = auth_client(owner).delete(detail_url(supplier))

        assert response.status_code == 409
        assert response.json()["code"] == "conflict"
        assert response.json()["message"] == (
            "Ce fournisseur est lié à 1 transaction et ne peut pas être supprimé."
        )

    def test_the_transaction_message_is_plural(self, auth_client, owner, site):
        from apps.stock.services import create_transaction

        supplier = SupplierFactory()
        for _ in range(2):
            create_transaction(
                type="IN",
                reason="PURCHASE",
                lines=[
                    {"article": ArticleFactory(), "quantity": 1, "unit_cost": None}
                ],
                user=owner,
                site=site,
                supplier=supplier,
            )

        response = auth_client(owner).delete(detail_url(supplier))

        assert response.json()["message"] == (
            "Ce fournisseur est lié à 2 transactions et ne peut pas être supprimé."
        )

    def test_articles_are_reported_before_transactions(self, auth_client, owner, site):
        """Both guards can trip at once. The article message is the one the
        user can act on — archive or reassign — so it wins."""
        from apps.stock.services import create_transaction

        supplier = SupplierFactory()
        ArticleFactory(supplier=supplier)
        create_transaction(
            type="IN",
            reason="PURCHASE",
            lines=[{"article": ArticleFactory(), "quantity": 1, "unit_cost": None}],
            user=owner,
            site=site,
            supplier=supplier,
        )

        response = auth_client(owner).delete(detail_url(supplier))

        assert "article" in response.json()["message"]


class TestPermissions:
    @pytest.mark.parametrize("method", ["post", "patch", "delete"])
    def test_a_cashier_may_not_write(self, auth_client, cashier, method):
        supplier = SupplierFactory()
        client = auth_client(cashier)
        url = LIST_URL if method == "post" else detail_url(supplier)
        response = getattr(client, method)(url, {"name": "X"}, format="json")
        assert response.status_code == 403

    def test_a_manager_may_not_delete(self, auth_client, manager):
        supplier = SupplierFactory()
        assert auth_client(manager).delete(detail_url(supplier)).status_code == 403
