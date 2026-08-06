"""Category endpoints.

Payload assertions are against the frontend's `Category` type in
`types/domain.ts`: exactly `id`, `name`, `description`, `articleCount`.
"""

import uuid

import pytest

from apps.catalogue.models import Category
from apps.catalogue.tests.factories import ArticleFactory, CategoryFactory

pytestmark = pytest.mark.django_db

LIST_URL = "/api/categories/"


def detail_url(category) -> str:
    return f"{LIST_URL}{category.id}/"


class TestRead:
    def test_the_payload_matches_the_frontend_type(self, auth_client, cashier):
        category = CategoryFactory(name="Boissons", description="Sodas et eaux.")
        ArticleFactory(category=category)
        ArticleFactory(category=category)

        response = auth_client(cashier).get(LIST_URL)

        assert response.status_code == 200
        assert set(response.json()["results"][0]) == {
            "id",
            "name",
            "description",
            "articleCount",
        }
        row = response.json()["results"][0]
        assert row["name"] == "Boissons"
        assert row["description"] == "Sodas et eaux."
        assert row["articleCount"] == 2

    def test_article_count_includes_archived_articles(self, auth_client, cashier):
        """`withArticleCounts` in services/categories.ts does not filter on
        isActive, and the delete guard counts the same population."""
        category = CategoryFactory()
        ArticleFactory(category=category, is_active=True)
        ArticleFactory(category=category, is_active=False)

        response = auth_client(cashier).get(LIST_URL)

        assert response.json()["results"][0]["articleCount"] == 2

    def test_an_empty_description_serialises_as_null(self, auth_client, cashier):
        CategoryFactory(description=None)
        response = auth_client(cashier).get(LIST_URL)
        assert response.json()["results"][0]["description"] is None

    def test_the_envelope_is_the_frontend_paginated_shape(self, auth_client, cashier):
        CategoryFactory()
        response = auth_client(cashier).get(LIST_URL)
        assert set(response.json()) == {"count", "next", "previous", "results"}

    def test_ordered_by_name(self, auth_client, cashier):
        CategoryFactory(name="Épicerie")
        CategoryFactory(name="Boissons")
        response = auth_client(cashier).get(LIST_URL)
        assert [r["name"] for r in response.json()["results"]] == [
            "Boissons",
            "Épicerie",
        ]

    def test_search_covers_name_and_description(self, auth_client, cashier):
        CategoryFactory(name="Boissons", description="Sodas.")
        CategoryFactory(name="Épicerie", description="Farine et sucre.")

        by_name = auth_client(cashier).get(f"{LIST_URL}?search=boiss")
        assert by_name.json()["count"] == 1

        by_description = auth_client(cashier).get(f"{LIST_URL}?search=farine")
        assert by_description.json()["count"] == 1

    def test_retrieve(self, auth_client, cashier):
        category = CategoryFactory(name="Boissons")
        response = auth_client(cashier).get(detail_url(category))
        assert response.status_code == 200
        assert response.json()["name"] == "Boissons"

    def test_unknown_id_is_404_with_the_envelope(self, auth_client, cashier):
        response = auth_client(cashier).get(f"{LIST_URL}{uuid.uuid4()}/")
        assert response.status_code == 404
        assert response.json()["code"] == "not_found"

    def test_anonymous_is_rejected(self, api_client):
        response = api_client.get(LIST_URL)
        assert response.status_code == 401
        assert response.json()["code"] == "authentication_failed"


class TestWrite:
    def test_a_manager_can_create(self, auth_client, manager):
        response = auth_client(manager).post(
            LIST_URL, {"name": "Boissons", "description": "Sodas."}, format="json"
        )
        assert response.status_code == 201
        assert response.json()["articleCount"] == 0
        assert Category.objects.count() == 1

    def test_an_empty_description_is_stored_as_null(self, auth_client, manager):
        response = auth_client(manager).post(
            LIST_URL, {"name": "Boissons", "description": ""}, format="json"
        )
        assert response.status_code == 201
        assert Category.objects.get().description is None

    def test_a_manager_can_update(self, auth_client, manager):
        category = CategoryFactory(name="Boissons")
        response = auth_client(manager).patch(
            detail_url(category), {"name": "Boissons fraîches"}, format="json"
        )
        assert response.status_code == 200
        category.refresh_from_db()
        assert category.name == "Boissons fraîches"

    def test_a_duplicate_name_is_rejected_case_insensitively(
        self, auth_client, manager
    ):
        CategoryFactory(name="Boissons")
        response = auth_client(manager).post(
            LIST_URL, {"name": "BOISSONS", "description": ""}, format="json"
        )
        assert response.status_code == 400
        assert response.json()["fieldErrors"]["name"] == [
            "Une catégorie porte déjà ce nom."
        ]

    def test_a_category_does_not_clash_with_itself_on_update(
        self, auth_client, manager
    ):
        category = CategoryFactory(name="Boissons")
        response = auth_client(manager).patch(
            detail_url(category), {"description": "Mis à jour."}, format="json"
        )
        assert response.status_code == 200

    def test_a_short_name_is_rejected(self, auth_client, manager):
        response = auth_client(manager).post(
            LIST_URL, {"name": "B", "description": ""}, format="json"
        )
        assert response.status_code == 400
        assert "name" in response.json()["fieldErrors"]


class TestDelete:
    def test_an_owner_can_delete_an_empty_category(self, auth_client, owner):
        category = CategoryFactory()
        response = auth_client(owner).delete(detail_url(category))
        assert response.status_code == 204
        assert Category.objects.count() == 0

    def test_a_category_with_articles_is_409(self, auth_client, owner):
        category = CategoryFactory()
        ArticleFactory(category=category)
        ArticleFactory(category=category)
        ArticleFactory(category=category)

        response = auth_client(owner).delete(detail_url(category))

        assert response.status_code == 409
        assert response.json()["code"] == "conflict"
        assert response.json()["message"] == (
            "Cette catégorie contient 3 articles et ne peut pas être supprimée."
        )

    def test_the_message_is_singular_for_one_article(self, auth_client, owner):
        category = CategoryFactory()
        ArticleFactory(category=category)
        response = auth_client(owner).delete(detail_url(category))
        assert response.json()["message"] == (
            "Cette catégorie contient 1 article et ne peut pas être supprimée."
        )


class TestPermissions:
    def test_a_cashier_may_read(self, auth_client, cashier):
        CategoryFactory()
        assert auth_client(cashier).get(LIST_URL).status_code == 200

    @pytest.mark.parametrize("method", ["post", "patch", "delete"])
    def test_a_cashier_may_not_write(self, auth_client, cashier, method):
        category = CategoryFactory()
        client = auth_client(cashier)
        url = LIST_URL if method == "post" else detail_url(category)
        response = getattr(client, method)(url, {"name": "X"}, format="json")

        assert response.status_code == 403
        assert response.json()["code"] == "permission_denied"

    def test_a_manager_may_not_delete(self, auth_client, manager):
        category = CategoryFactory()
        response = auth_client(manager).delete(detail_url(category))
        assert response.status_code == 403
        assert response.json()["code"] == "permission_denied"

    def test_an_owner_may_do_everything(self, auth_client, owner):
        response = auth_client(owner).post(
            LIST_URL, {"name": "Boissons", "description": ""}, format="json"
        )
        assert response.status_code == 201
