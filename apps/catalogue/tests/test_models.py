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
from apps.common.models import DocumentSequence

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


class TestGeneratedSku:
    """The SKU is allocated once, at creation, and never changes."""

    def test_a_new_article_gets_a_generated_sku(self):
        article = Article.objects.create(
            name="Sucre blanc", category=CategoryFactory()
        )
        assert article.sku == "ART-00001"

    def test_consecutive_articles_get_consecutive_skus(self):
        category = CategoryFactory()
        first = Article.objects.create(name="Sucre", category=category)
        second = Article.objects.create(name="Farine", category=category)
        assert [first.sku, second.sku] == ["ART-00001", "ART-00002"]

    def test_an_explicit_sku_is_kept(self):
        """Legacy rows and the factories carry hand-typed references."""
        article = Article.objects.create(
            name="Sucre", category=CategoryFactory(), sku="EPI-001"
        )
        assert article.sku == "EPI-001"
        # The seeding migration creates this row at 0 on every database,
        # including the test one. Nothing here should have incremented it.
        assert DocumentSequence.objects.get(prefix="ART", year=0).last_number == 0

    def test_updating_an_article_does_not_allocate_a_new_number(self):
        """The decoy for `_state.adding`. Without that guard an update would
        burn a counter value, and the next article created would be ART-00003
        rather than ART-00002."""
        article = Article.objects.create(name="Sucre", category=CategoryFactory())
        article.name = "Sucre roux"
        article.save()

        article.refresh_from_db()
        assert article.sku == "ART-00001"
        assert DocumentSequence.objects.get(prefix="ART", year=0).last_number == 1
