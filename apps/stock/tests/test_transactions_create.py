"""POST /api/stock/transactions/."""

import uuid

import pytest

from apps.catalogue.tests.factories import ArticleFactory, SupplierFactory
from apps.stock.models import StockLevel, StockMovement, StockTransaction
from apps.stock.tests.factories import StockLevelFactory

pytestmark = pytest.mark.django_db

URL = "/api/stock/transactions/"


def body(lines, **overrides):
    payload = {
        "type": "IN",
        "reason": "PURCHASE",
        "supplierId": None,
        "reference": None,
        "note": None,
        "lines": lines,
    }
    payload.update(overrides)
    return payload


def line(article, quantity=5, unit_cost=None):
    return {
        "articleId": str(article.id),
        "quantity": quantity,
        "unitCost": unit_cost,
    }


class TestCreate:
    def test_a_manager_can_create(self, auth_client, manager, site):
        first, second = ArticleFactory(), ArticleFactory()

        response = auth_client(manager).post(
            URL, body([line(first, 4), line(second, 6)]), format="json"
        )

        assert response.status_code == 201
        assert response.json()["reference"].startswith("TR-")
        assert response.json()["lineCount"] == 2
        assert response.json()["totalQuantity"] == 10
        assert StockMovement.objects.count() == 2

    def test_the_payload_matches_the_frontend_type(self, auth_client, manager, site):
        response = auth_client(manager).post(
            URL, body([line(ArticleFactory())]), format="json"
        )

        assert set(response.json()) == {
            "id",
            "reference",
            "siteId",
            "userReference",
            "type",
            "reason",
            "supplierId",
            "supplierName",
            "note",
            "lineCount",
            "totalQuantity",
            "userId",
            "userName",
            "createdAt",
        }

    def test_a_supplier_is_recorded_by_id_and_name(self, auth_client, manager, site):
        supplier = SupplierFactory(name="Brasimba")

        response = auth_client(manager).post(
            URL,
            body([line(ArticleFactory())], supplierId=str(supplier.id)),
            format="json",
        )

        assert response.json()["supplierId"] == str(supplier.id)
        assert response.json()["supplierName"] == "Brasimba"

    def test_no_supplier_serialises_as_null(self, auth_client, manager, site):
        response = auth_client(manager).post(
            URL, body([line(ArticleFactory())]), format="json"
        )
        assert response.json()["supplierId"] is None
        assert response.json()["supplierName"] is None

    def test_the_user_reference_is_kept_separate_from_the_tr_number(
        self, auth_client, manager, site
    ):
        response = auth_client(manager).post(
            URL, body([line(ArticleFactory())], reference="BL-42"), format="json"
        )

        assert response.json()["reference"].startswith("TR-")
        assert response.json()["userReference"] == "BL-42"

    def test_a_cashier_may_not_create(self, auth_client, cashier, site):
        response = auth_client(cashier).post(
            URL, body([line(ArticleFactory())]), format="json"
        )
        assert response.status_code == 403
        assert response.json()["code"] == "permission_denied"


class TestLineValidation:
    def test_no_lines_is_rejected(self, auth_client, manager, site):
        response = auth_client(manager).post(URL, body([]), format="json")

        assert response.status_code == 400
        assert response.json()["fieldErrors"]["lines"] == [
            "Ajoutez au moins un article à la transaction."
        ]

    def test_a_duplicate_article_is_rejected(self, auth_client, manager, site):
        """Rejected rather than summed: summing makes the ledger ambiguous and
        raises an ordering question with no good answer."""
        article = ArticleFactory()

        response = auth_client(manager).post(
            URL, body([line(article), line(article)]), format="json"
        )

        assert response.status_code == 400
        assert response.json()["fieldErrors"]["lines.1.articleId"] == [
            "Cet article est déjà présent dans la transaction."
        ]

    def test_an_unknown_article_is_rejected_on_its_row(
        self, auth_client, manager, site
    ):
        response = auth_client(manager).post(
            URL,
            body(
                [
                    line(ArticleFactory()),
                    {"articleId": str(uuid.uuid4()), "quantity": 1, "unitCost": None},
                ]
            ),
            format="json",
        )

        assert response.status_code == 400
        assert response.json()["fieldErrors"]["lines.1.articleId"] == [
            "Cet article n'existe plus."
        ]

    def test_a_negative_quantity_is_rejected_on_its_row(
        self, auth_client, manager, site
    ):
        response = auth_client(manager).post(
            URL,
            body([line(ArticleFactory()), line(ArticleFactory(), quantity=-3)]),
            format="json",
        )

        assert response.status_code == 400
        assert response.json()["fieldErrors"]["lines.1.quantity"] == [
            "La quantité doit être un nombre entier positif."
        ]

    def test_zero_is_rejected_for_in_and_out(self, auth_client, manager, site):
        response = auth_client(manager).post(
            URL, body([line(ArticleFactory(), quantity=0)]), format="json"
        )

        assert response.status_code == 400
        assert response.json()["fieldErrors"]["lines.0.quantity"] == [
            "La quantité doit être supérieure à zéro."
        ]

    def test_zero_is_allowed_for_an_adjustment(self, auth_client, manager, site):
        article = ArticleFactory()
        StockLevelFactory(article=article, site=site, quantity=7)

        response = auth_client(manager).post(
            URL,
            body(
                [line(article, quantity=0)],
                type="ADJUSTMENT",
                reason="COUNT_CORRECTION",
            ),
            format="json",
        )

        assert response.status_code == 201
        assert StockLevel.objects.get(article=article).quantity == 0

    def test_insufficient_stock_names_the_offending_row(
        self, auth_client, manager, site
    ):
        good, bad = ArticleFactory(), ArticleFactory()
        StockLevelFactory(article=good, site=site, quantity=50)
        StockLevelFactory(article=bad, site=site, quantity=2)

        response = auth_client(manager).post(
            URL,
            body([line(good, 10), line(bad, 99)], type="OUT", reason="SALE"),
            format="json",
        )

        assert response.status_code == 400
        assert response.json()["fieldErrors"]["lines.1.quantity"] == [
            "Stock insuffisant : 2 unité(s) disponible(s) actuellement."
        ]
        assert StockTransaction.objects.count() == 0
        assert StockLevel.objects.get(article=good).quantity == 50

    def test_an_over_long_reference_is_rejected(self, auth_client, manager, site):
        response = auth_client(manager).post(
            URL, body([line(ArticleFactory())], reference="X" * 41), format="json"
        )
        assert response.status_code == 400
        assert "reference" in response.json()["fieldErrors"]


class TestImmutability:
    def test_patch_on_the_list_route_is_405(self, auth_client, manager, site):
        assert auth_client(manager).patch(URL, {}, format="json").status_code == 405

    def test_patch_on_a_transaction_is_405(self, auth_client, manager, site):
        created = auth_client(manager).post(
            URL, body([line(ArticleFactory())]), format="json"
        )
        detail = f"{URL}{created.json()['id']}/"

        assert auth_client(manager).patch(detail, {}, format="json").status_code == 405

    def test_delete_on_a_transaction_is_405(self, auth_client, owner, manager, site):
        created = auth_client(manager).post(
            URL, body([line(ArticleFactory())]), format="json"
        )
        detail = f"{URL}{created.json()['id']}/"

        assert auth_client(owner).delete(detail).status_code == 405
