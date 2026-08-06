from decimal import Decimal

import factory
from django.utils import timezone
from factory.django import DjangoModelFactory

from apps.accounts.tests.factories import SiteFactory, UserFactory
from apps.catalogue.tests.factories import ArticleFactory
from apps.sales.models import Customer, Payment, Sale, SaleLine


class CustomerFactory(DjangoModelFactory):
    class Meta:
        model = Customer

    name = factory.Sequence(lambda n: f"Client {n}")
    contact_name = "Marie Kabeya"
    email = factory.Sequence(lambda n: f"client{n}@exemple.cd")
    phone = "+243 990 333 444"
    address = "22 avenue des Volcans, Goma"
    tax_number = None
    notes = None
    is_active = True


class SaleFactory(DjangoModelFactory):
    class Meta:
        model = Sale

    reference = factory.Sequence(lambda n: f"FA-2026-{n + 1:04d}")
    site = factory.SubFactory(SiteFactory)
    user = factory.SubFactory(UserFactory)
    user_name = factory.LazyAttribute(lambda obj: obj.user.full_name)
    customer = None
    customer_name = None
    customer_address = None
    customer_tax_number = None
    status = Sale.Status.COMPLETED
    subtotal = 10_000
    discount = 0
    discount_rate = None
    total = 10_000
    vat_total = 1_379
    note = None


class SaleLineFactory(DjangoModelFactory):
    class Meta:
        model = SaleLine

    sale = factory.SubFactory(SaleFactory)
    article = factory.SubFactory(ArticleFactory)
    article_name = factory.LazyAttribute(lambda obj: obj.article.name)
    article_sku = factory.LazyAttribute(lambda obj: obj.article.sku)
    unit = factory.LazyAttribute(lambda obj: obj.article.unit)
    quantity = 2
    unit_price = 5_000
    unit_cost = 3_000
    vat_rate = Decimal("16.00")
    line_total = 10_000
    discount_share = 0
    vat_amount = 1_379


class PaymentFactory(DjangoModelFactory):
    class Meta:
        model = Payment

    sale = factory.SubFactory(SaleFactory)
    user = factory.SubFactory(UserFactory)
    user_name = factory.LazyAttribute(lambda obj: obj.user.full_name)
    amount = 5_000
    method = Payment.Method.CASH
    paid_at = factory.LazyFunction(timezone.now)
    reference = None
    note = None
