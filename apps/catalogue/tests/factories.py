"""Catalogue factories.

Imported by later tasks and by sub-projects 3–6, so the signatures are
effectively public. Keep the defaults realistic — a Goma corner shop.
"""

from decimal import Decimal

import factory
from factory.django import DjangoModelFactory

from apps.catalogue.models import Article, Category, Supplier


class CategoryFactory(DjangoModelFactory):
    class Meta:
        model = Category

    name = factory.Sequence(lambda n: f"Catégorie {n}")
    description = "Produits de première nécessité."


class SupplierFactory(DjangoModelFactory):
    class Meta:
        model = Supplier

    name = factory.Sequence(lambda n: f"Fournisseur {n}")
    contact_name = "Jean Kabila"
    email = factory.Sequence(lambda n: f"contact{n}@fournisseur.cd")
    phone = "+243 990 111 222"
    address = "18 avenue du Lac, Goma"
    notes = None
    is_active = True


class ArticleFactory(DjangoModelFactory):
    class Meta:
        model = Article

    sku = factory.Sequence(lambda n: f"ART-{n:04d}")
    barcode = None
    name = factory.Sequence(lambda n: f"Article {n}")
    description = None
    category = factory.SubFactory(CategoryFactory)
    supplier = None
    unit = Article.Unit.PIECE
    purchase_price = 1000
    sale_price = 1500
    vat_rate = Decimal("16.00")
    is_active = True
