"""Ordering by the French collation key.

The bug this closes was user-visible: with `ordering = ["name"]` on SQLite,
`Épicerie` and `Œufs` sorted after `Zeste`, and the frontend renders list
responses in API order.
"""

import pytest

from apps.catalogue.models import Article, Category, Supplier
from apps.catalogue.name_sort import rebuild_name_sort
from apps.catalogue.tests.factories import (
    ArticleFactory,
    CategoryFactory,
    SupplierFactory,
)

pytestmark = pytest.mark.django_db

ACCENTED = ["Zeste", "Épicerie", "Fruits", "Œufs", "Oignons"]
IN_FRENCH_ORDER = ["Épicerie", "Fruits", "Œufs", "Oignons", "Zeste"]


class TestTheColumn:
    def test_save_populates_the_key(self):
        category = CategoryFactory(name="Épicerie")
        category.refresh_from_db()
        assert category.name_sort == "epicerie"

    def test_a_rename_updates_the_key(self):
        category = CategoryFactory(name="Épicerie")
        category.name = "Œufs"
        category.save()
        category.refresh_from_db()
        assert category.name_sort == "oeufs"

    def test_the_key_fits_a_name_of_only_ligatures(self):
        # 60 x "Œ" keys to 120 characters: the column must not truncate.
        name = "Œ" * 60
        category = CategoryFactory(name=name)
        category.refresh_from_db()
        assert category.name_sort == "oe" * 60

    @pytest.mark.parametrize(
        "factory,model",
        [
            (CategoryFactory, Category),
            (SupplierFactory, Supplier),
        ],
    )
    def test_default_ordering_is_french(self, factory, model):
        for name in ACCENTED:
            factory(name=name)
        assert [row.name for row in model.objects.all()] == IN_FRENCH_ORDER

    def test_article_default_ordering_is_french(self):
        category = CategoryFactory()
        for name in ACCENTED:
            ArticleFactory(name=name, category=category)
        assert [row.name for row in Article.objects.all()] == IN_FRENCH_ORDER


class TestTheBackfill:
    def test_it_populates_rows_written_without_the_key(self):
        for name in ACCENTED:
            CategoryFactory(name=name)
        # Simulate rows that predate the column.
        Category.objects.update(name_sort="")

        rebuild_name_sort(Category)

        assert [row.name for row in Category.objects.all()] == IN_FRENCH_ORDER


class TestTheEndpoints:
    """The default path and the explicit `?ordering=name` path both alias."""

    @pytest.fixture
    def categories(self):
        for name in ACCENTED:
            CategoryFactory(name=name)

    def test_the_default_ordering_is_french(self, auth_client, manager, categories):
        response = auth_client(manager).get("/api/categories/")
        assert response.status_code == 200
        names = [row["name"] for row in response.json()["results"]]
        assert names == IN_FRENCH_ORDER

    def test_explicit_ordering_by_name_is_french(
        self, auth_client, manager, categories
    ):
        response = auth_client(manager).get("/api/categories/?ordering=name")
        assert response.status_code == 200
        names = [row["name"] for row in response.json()["results"]]
        assert names == IN_FRENCH_ORDER

    def test_descending_reverses_it(self, auth_client, manager, categories):
        response = auth_client(manager).get("/api/categories/?ordering=-name")
        assert response.status_code == 200
        names = [row["name"] for row in response.json()["results"]]
        assert names == list(reversed(IN_FRENCH_ORDER))

    def test_name_sort_is_not_serialized(self, auth_client, manager, categories):
        row = auth_client(manager).get("/api/categories/").json()["results"][0]
        assert "nameSort" not in row
        assert "name_sort" not in row

    def test_an_unknown_ordering_is_still_rejected(
        self, auth_client, manager, categories
    ):
        response = auth_client(manager).get("/api/categories/?ordering=nope")
        assert response.status_code == 400
        # The project's exception handler wraps field errors in `fieldErrors`.
        assert "ordering" in response.json()["fieldErrors"]
