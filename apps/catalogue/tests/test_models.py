"""Catalogue model invariants.

Case-insensitive uniqueness is enforced by a functional index, not only by a
serializer. The serializer produces the French message a user reads; the index
is what makes the guarantee true when two requests race.
"""

import pytest
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError

from apps.catalogue.models import Article, Category, Supplier
from apps.catalogue.tests.factories import (
    ArticleFactory,
    CategoryFactory,
    SupplierFactory,
)

pytestmark = pytest.mark.django_db


class TestCategory:
    def test_names_differing_only_in_case_collide(self):
        CategoryFactory(name="Boissons")
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                Category.objects.create(name="BOISSONS")

    def test_distinct_names_coexist(self):
        CategoryFactory(name="Boissons")
        CategoryFactory(name="Épicerie")
        assert Category.objects.count() == 2

    def test_default_ordering_is_by_name(self):
        CategoryFactory(name="Épicerie")
        CategoryFactory(name="Boissons")
        assert [c.name for c in Category.objects.all()] == ["Boissons", "Épicerie"]

    def test_a_category_with_articles_cannot_be_deleted(self):
        article = ArticleFactory()
        with pytest.raises(ProtectedError):
            article.category.delete()


class TestSupplier:
    def test_names_differing_only_in_case_collide(self):
        SupplierFactory(name="Brasimba")
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                Supplier.objects.create(name="BRASIMBA")

    def test_a_supplier_with_articles_cannot_be_deleted(self):
        article = ArticleFactory(supplier=SupplierFactory())
        with pytest.raises(ProtectedError):
            article.supplier.delete()


class TestArticle:
    def test_skus_differing_only_in_case_collide(self):
        category = CategoryFactory()
        ArticleFactory(sku="BOI-001", category=category)
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                ArticleFactory(sku="boi-001", category=category)

    def test_barcodes_collide(self):
        ArticleFactory(barcode="1234567890123")
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                ArticleFactory(barcode="1234567890123")

    def test_many_articles_may_have_no_barcode(self):
        """NULL, not "".

        An empty string is a value that collides with itself, so a second
        barcode-less article would violate the unique constraint. NULL never
        compares equal to NULL.
        """
        ArticleFactory(barcode=None)
        ArticleFactory(barcode=None)
        assert Article.objects.filter(barcode__isnull=True).count() == 2

    def test_supplier_is_optional(self):
        article = ArticleFactory(supplier=None)
        assert article.supplier is None

    def test_vat_rate_keeps_two_decimal_places(self):
        from decimal import Decimal

        article = ArticleFactory(vat_rate=Decimal("5.50"))
        article.refresh_from_db()
        assert article.vat_rate == Decimal("5.50")

    def test_default_ordering_is_by_name(self):
        ArticleFactory(name="Sucre")
        ArticleFactory(name="Farine")
        assert [a.name for a in Article.objects.all()] == ["Farine", "Sucre"]
