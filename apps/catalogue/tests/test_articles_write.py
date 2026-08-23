"""Article writes: creation side effects, validation, delete guard."""

import pytest

from apps.catalogue.models import Article
from apps.catalogue.tests.factories import (
    ArticleFactory,
    CategoryFactory,
    SupplierFactory,
)
from apps.stock.models import StockLevel, StockMovement
from apps.stock.tests.factories import StockLevelFactory, StockMovementFactory

pytestmark = pytest.mark.django_db

LIST_URL = "/api/articles/"


def detail_url(article) -> str:
    return f"{LIST_URL}{article.id}/"


def payload(category, **overrides):
    body = {
        "barcode": None,
        "name": "Sucre blanc",
        "description": "Sac de 1 kg.",
        "categoryId": str(category.id),
        "supplierId": None,
        "unit": "KG",
        "purchasePrice": 1000,
        "salePrice": 1500,
        "vatRate": 16,
        "isActive": True,
        "initialQuantity": 0,
        "reorderThreshold": 10,
    }
    body.update(overrides)
    return body


class TestCreate:
    def test_a_manager_can_create(self, auth_client, manager, site):
        category = CategoryFactory()
        response = auth_client(manager).post(LIST_URL, payload(category), format="json")

        assert response.status_code == 201
        assert response.json()["sku"] == "ART-00001"
        assert response.json()["stock"]["reorderThreshold"] == 10

    def test_a_client_supplied_sku_is_ignored(self, auth_client, manager, site):
        """The decoy: asserting only the ART- pattern would still pass if the
        client's value were honoured whenever it happened to look generated."""
        category = CategoryFactory()
        response = auth_client(manager).post(
            LIST_URL, payload(category, sku="HACK-1"), format="json"
        )

        assert response.status_code == 201
        assert response.json()["sku"] == "ART-00001"
        assert not Article.objects.filter(sku="HACK-1").exists()

    def test_creating_without_a_sku_is_accepted(self, auth_client, manager, site):
        category = CategoryFactory()
        response = auth_client(manager).post(LIST_URL, payload(category), format="json")
        assert response.status_code == 201

    def test_a_stock_level_is_written(self, auth_client, manager, site):
        category = CategoryFactory()
        auth_client(manager).post(
            LIST_URL, payload(category, reorderThreshold=25), format="json"
        )

        level = StockLevel.objects.get()
        assert level.site == site
        assert level.quantity == 0
        assert level.reorder_threshold == 25

    def test_no_opening_movement_when_initial_quantity_is_zero(
        self, auth_client, manager, site
    ):
        category = CategoryFactory()
        auth_client(manager).post(
            LIST_URL, payload(category, initialQuantity=0), format="json"
        )
        assert StockMovement.objects.count() == 0

    def test_an_opening_movement_is_written(self, auth_client, manager, site):
        category = CategoryFactory()
        response = auth_client(manager).post(
            LIST_URL,
            payload(category, initialQuantity=40, purchasePrice=1200),
            format="json",
        )

        assert response.json()["stock"]["quantity"] == 40

        movement = StockMovement.objects.get()
        assert movement.type == "IN"
        assert movement.reason == "PURCHASE"
        assert movement.quantity == 40
        assert movement.quantity_before == 0
        assert movement.quantity_after == 40
        assert movement.unit_cost == 1200
        assert movement.note == "Stock initial"
        assert movement.user == manager
        assert movement.user_name == manager.full_name

    def test_creation_is_atomic(self, auth_client, manager, site):
        """If the movement write fails the article must not survive.

        The failure surfaces as a 500 rather than an exception: the error
        envelope's handler turns any unhandled exception into one, so
        `pytest.raises` would never see it. What matters is the rollback.
        """
        from unittest import mock

        category = CategoryFactory()
        with mock.patch(
            "apps.stock.models.StockMovement.objects.create",
            side_effect=RuntimeError("boom"),
        ):
            response = auth_client(manager).post(
                LIST_URL, payload(category, initialQuantity=5), format="json"
            )

        assert response.status_code == 500
        assert Article.objects.count() == 0
        assert StockLevel.objects.count() == 0


class TestValidation:
    # The SKU has no validator here any more: it is allocated by
    # Article.save() and read-only on the serializer, so a client cannot send
    # a duplicate. `article_sku_unique_ci` is the remaining guarantee, covered
    # by test_skus_differing_only_in_case_collide in test_models.py.

    def test_a_duplicate_barcode_is_rejected(self, auth_client, manager, site):
        category = CategoryFactory()
        ArticleFactory(barcode="1234567890123")
        response = auth_client(manager).post(
            LIST_URL, payload(category, barcode="1234567890123"), format="json"
        )
        assert response.status_code == 400
        assert response.json()["fieldErrors"]["barcode"] == [
            "Ce code-barres est déjà utilisé."
        ]

    @pytest.mark.parametrize("barcode", ["123", "12345678901234", "abcdefgh"])
    def test_a_malformed_barcode_is_rejected(self, auth_client, manager, site, barcode):
        category = CategoryFactory()
        response = auth_client(manager).post(
            LIST_URL, payload(category, barcode=barcode), format="json"
        )
        assert response.status_code == 400
        assert "barcode" in response.json()["fieldErrors"]

    @pytest.mark.parametrize("barcode", ["12345678", "1234567890123"])
    def test_eight_and_thirteen_digit_barcodes_are_accepted(
        self, auth_client, manager, site, barcode
    ):
        category = CategoryFactory()
        response = auth_client(manager).post(
            LIST_URL, payload(category, barcode=barcode), format="json"
        )
        assert response.status_code == 201

    def test_an_empty_barcode_is_stored_as_null(self, auth_client, manager, site):
        category = CategoryFactory()
        auth_client(manager).post(LIST_URL, payload(category, barcode=""), format="json")
        assert Article.objects.get().barcode is None

    def test_a_sale_price_below_the_purchase_price_is_rejected(
        self, auth_client, manager, site
    ):
        category = CategoryFactory()
        response = auth_client(manager).post(
            LIST_URL,
            payload(category, purchasePrice=2000, salePrice=1500),
            format="json",
        )
        assert response.status_code == 400
        assert response.json()["fieldErrors"]["salePrice"] == [
            "Le prix de vente doit être supérieur ou égal au prix d'achat."
        ]

    def test_equal_prices_are_accepted(self, auth_client, manager, site):
        category = CategoryFactory()
        response = auth_client(manager).post(
            LIST_URL,
            payload(category, purchasePrice=1500, salePrice=1500),
            format="json",
        )
        assert response.status_code == 201

    @pytest.mark.parametrize("rate", [-1, 101])
    def test_an_out_of_range_vat_rate_is_rejected(
        self, auth_client, manager, site, rate
    ):
        category = CategoryFactory()
        response = auth_client(manager).post(
            LIST_URL, payload(category, vatRate=rate), format="json"
        )
        assert response.status_code == 400
        assert "vatRate" in response.json()["fieldErrors"]

    def test_a_decimal_vat_rate_is_accepted(self, auth_client, manager, site):
        category = CategoryFactory()
        response = auth_client(manager).post(
            LIST_URL, payload(category, vatRate=5.5), format="json"
        )
        assert response.status_code == 201
        assert response.json()["vatRate"] == 5.5


class TestUpdate:
    def test_the_reorder_threshold_is_editable(self, auth_client, manager, site):
        article = ArticleFactory()
        StockLevelFactory(article=article, site=site, quantity=30, reorder_threshold=5)

        response = auth_client(manager).patch(
            detail_url(article), {"reorderThreshold": 50}, format="json"
        )

        assert response.status_code == 200
        assert response.json()["stock"]["reorderThreshold"] == 50
        assert response.json()["stock"]["quantity"] == 30

    def test_the_threshold_is_editable_on_an_article_with_no_level(
        self, auth_client, manager, site
    ):
        """An article seeded outside the API has no level row of its own.

        `seeder.py` builds articles with `Article.objects.create`, which does
        not write the `StockLevel` the serializer's `create` would. Filtering
        for a row that was never written matches nothing and updates nothing,
        so the request answered 200 while saving the threshold nowhere — a
        write that reports success and does not happen.
        """
        article = ArticleFactory()
        assert not StockLevel.objects.filter(article=article).exists()

        response = auth_client(manager).patch(
            detail_url(article), {"reorderThreshold": 50}, format="json"
        )

        assert response.status_code == 200
        assert response.json()["stock"]["reorderThreshold"] == 50
        assert StockLevel.objects.get(article=article, site=site).quantity == 0

    def test_updating_the_threshold_does_not_touch_the_quantity(
        self, auth_client, manager, site
    ):
        article = ArticleFactory()
        StockLevelFactory(article=article, site=site, quantity=30)
        auth_client(manager).patch(
            detail_url(article), {"reorderThreshold": 50}, format="json"
        )
        assert StockLevel.objects.get().quantity == 30

    def test_initial_quantity_is_ignored_on_update(self, auth_client, manager, site):
        """Once an article exists, stock changes only through movements."""
        article = ArticleFactory()
        StockLevelFactory(article=article, site=site, quantity=30)

        auth_client(manager).patch(
            detail_url(article), {"initialQuantity": 999}, format="json"
        )

        assert StockLevel.objects.get().quantity == 30
        assert StockMovement.objects.count() == 0

    def test_the_sku_cannot_be_changed(self, auth_client, manager, site):
        article = ArticleFactory(sku="LEG-0001")
        response = auth_client(manager).patch(
            detail_url(article), {"sku": "AUTRE-1"}, format="json"
        )

        assert response.status_code == 200
        article.refresh_from_db()
        assert article.sku == "LEG-0001"

    def test_a_generated_sku_cannot_be_changed(self, auth_client, manager, site):
        """Both paths, because a legacy SKU and a generated one reach the
        serializer through different histories."""
        article = Article.objects.create(name="Sucre", category=CategoryFactory())
        auth_client(manager).patch(
            detail_url(article), {"sku": "AUTRE-1"}, format="json"
        )
        article.refresh_from_db()
        assert article.sku == "ART-00001"

    def test_an_article_can_be_archived(self, auth_client, manager, site):
        """The frontend's `archiveArticle` is exactly this PATCH."""
        article = ArticleFactory(is_active=True)
        response = auth_client(manager).patch(
            detail_url(article), {"isActive": False}, format="json"
        )
        assert response.status_code == 200
        article.refresh_from_db()
        assert article.is_active is False


class TestDelete:
    def test_an_owner_can_delete_an_article_with_no_movements(
        self, auth_client, owner, site
    ):
        article = ArticleFactory()
        StockLevelFactory(article=article, site=site)

        response = auth_client(owner).delete(detail_url(article))

        assert response.status_code == 204
        assert Article.objects.count() == 0
        assert StockLevel.objects.count() == 0

    def test_an_article_with_movements_is_409(self, auth_client, owner, site):
        article = ArticleFactory()
        StockMovementFactory(article=article, site=site, user=owner)

        response = auth_client(owner).delete(detail_url(article))

        assert response.status_code == 409
        assert response.json()["code"] == "conflict"
        assert response.json()["message"] == (
            "Cet article possède un historique de mouvements et ne peut pas "
            "être supprimé. Vous pouvez l'archiver."
        )

    def test_an_article_created_with_opening_stock_can_never_be_deleted(
        self, auth_client, owner, manager, site
    ):
        """Inherited from the frontend, which behaves identically. Worth a
        test so nobody 'fixes' it later without deciding to."""
        category = CategoryFactory()
        created = auth_client(manager).post(
            LIST_URL, payload(category, initialQuantity=10), format="json"
        )

        response = auth_client(owner).delete(f"{LIST_URL}{created.json()['id']}/")

        assert response.status_code == 409
