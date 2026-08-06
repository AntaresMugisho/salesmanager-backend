"""Sales model invariants."""

import pytest
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError

from apps.catalogue.tests.factories import ArticleFactory
from apps.sales.models import Customer, Sale, SaleLine
from apps.sales.tests.factories import (
    CustomerFactory,
    PaymentFactory,
    SaleFactory,
    SaleLineFactory,
)
from apps.stock.tests.factories import StockMovementFactory

pytestmark = pytest.mark.django_db


class TestCustomer:
    def test_names_differing_only_in_case_collide(self):
        CustomerFactory(name="Kivu Market")
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                Customer.objects.create(name="KIVU MARKET")

    def test_default_ordering_is_by_name(self):
        CustomerFactory(name="Zeta")
        CustomerFactory(name="Alpha")
        assert [c.name for c in Customer.objects.all()] == ["Alpha", "Zeta"]

    def test_a_customer_with_sales_cannot_be_deleted(self, site, owner):
        customer = CustomerFactory()
        SaleFactory(customer=customer, user=owner, site=site)
        with pytest.raises(ProtectedError):
            customer.delete()


class TestSale:
    def test_references_are_unique(self, site, owner):
        SaleFactory(reference="FA-2026-0001", user=owner, site=site)
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                SaleFactory(reference="FA-2026-0001", user=owner, site=site)

    def test_the_customer_is_optional(self, site, owner):
        """Null for a « client de passage »."""
        assert SaleFactory(customer=None, user=owner, site=site).customer is None

    def test_the_billing_block_is_snapshotted(self, site, owner):
        """An invoice is a legal document: a customer moving must not rewrite
        the address on last quarter's invoices."""
        customer = CustomerFactory(name="Kivu Market", address="10 av. du Lac")
        sale = SaleFactory(
            customer=customer,
            customer_name="Kivu Market",
            customer_address="10 av. du Lac",
            user=owner,
            site=site,
        )

        customer.name = "Kivu Market SARL"
        customer.address = "99 boulevard Neuf"
        customer.save()
        sale.refresh_from_db()

        assert sale.customer_name == "Kivu Market"
        assert sale.customer_address == "10 av. du Lac"

    def test_a_user_with_sales_cannot_be_deleted(self, site, owner):
        SaleFactory(user=owner, site=site)
        with pytest.raises(ProtectedError):
            owner.delete()

    def test_newest_first(self, site, owner):
        first = SaleFactory(reference="FA-2026-0001", user=owner, site=site)
        second = SaleFactory(reference="FA-2026-0002", user=owner, site=site)
        assert list(Sale.objects.all()) == [second, first]


class TestSaleLine:
    def test_deleting_a_sale_deletes_its_lines(self, site, owner):
        """CASCADE here, unlike everywhere else: a line is part of the
        document. Nothing deletes a sale, so this never fires in practice."""
        sale = SaleFactory(user=owner, site=site)
        SaleLineFactory(sale=sale)
        sale.delete()
        assert SaleLine.objects.count() == 0

    def test_an_article_with_sale_lines_cannot_be_deleted(self, site, owner):
        line = SaleLineFactory(sale=SaleFactory(user=owner, site=site))
        with pytest.raises(ProtectedError):
            line.article.delete()

    def test_the_article_snapshot_survives_a_rename_and_reprice(self, site, owner):
        """unit_cost is the load-bearing one: sub-project 6 computes margin
        from it and never re-joins to the article."""
        article = ArticleFactory(name="Sucre", sku="EPI-1", purchase_price=800)
        line = SaleLineFactory(
            sale=SaleFactory(user=owner, site=site),
            article=article,
            article_name="Sucre",
            article_sku="EPI-1",
            unit_cost=800,
        )

        article.name = "Sucre roux"
        article.purchase_price = 1200
        article.save()
        line.refresh_from_db()

        assert line.article_name == "Sucre"
        assert line.unit_cost == 800


class TestPayment:
    def test_a_sale_with_payments_cannot_be_deleted(self, site, owner):
        """PROTECT, where SaleLine is CASCADE: a payment is a money record
        that should block a deletion rather than vanish inside one."""
        sale = SaleFactory(user=owner, site=site)
        PaymentFactory(sale=sale, user=owner)
        with pytest.raises(ProtectedError):
            sale.delete()

    def test_payments_reach_their_sale(self, site, owner):
        sale = SaleFactory(user=owner, site=site)
        first = PaymentFactory(sale=sale, user=owner)
        second = PaymentFactory(sale=sale, user=owner)
        assert set(sale.payments.all()) == {first, second}

    def test_the_user_name_is_denormalised(self, site, owner):
        payment = PaymentFactory(sale=SaleFactory(user=owner, site=site), user=owner)
        owner.full_name = "Nom Modifié"
        owner.save()
        payment.refresh_from_db()
        assert payment.user_name != "Nom Modifié"


class TestMovementLink:
    def test_a_movement_can_carry_a_sale(self, site, owner):
        sale = SaleFactory(user=owner, site=site)
        movement = StockMovementFactory(site=site, user=owner, sale=sale)
        assert list(sale.movements.all()) == [movement]

    def test_a_standalone_movement_has_no_sale(self, site, owner):
        assert StockMovementFactory(site=site, user=owner).sale is None

    def test_a_movement_carries_at_most_one_of_transaction_and_sale(self, site, owner):
        """Not enforced by a constraint — the writers never set both — but
        asserted so the assumption is written down somewhere executable."""
        from apps.stock.tests.factories import StockTransactionFactory

        with_sale = StockMovementFactory(
            site=site, user=owner, sale=SaleFactory(user=owner, site=site)
        )
        with_transaction = StockMovementFactory(
            site=site, user=owner, transaction=StockTransactionFactory(user=owner)
        )

        assert with_sale.transaction is None
        assert with_transaction.sale is None
