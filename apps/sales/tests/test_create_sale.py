"""Sale creation: snapshots, totals, stock, numbering, atomicity."""

from decimal import Decimal

import pytest
from rest_framework.serializers import ValidationError

from apps.catalogue.tests.factories import ArticleFactory
from apps.common.models import DocumentSequence
from apps.sales.models import Sale, SaleLine
from apps.sales.services import create_sale
from apps.sales.tests.factories import CustomerFactory
from apps.stock.models import StockLevel, StockMovement
from apps.stock.tests.factories import StockLevelFactory

pytestmark = pytest.mark.django_db


def stocked(site, quantity=100, **kwargs):
    article = ArticleFactory(**kwargs)
    StockLevelFactory(article=article, site=site, quantity=quantity)
    return article


def line(article, quantity=2, unit_price=5_000):
    return {"article": article, "quantity": quantity, "unit_price": unit_price}


def build(site, user, lines, **kwargs):
    return create_sale(lines=lines, user=user, site=site, **kwargs)


class TestHeader:
    def test_the_reference_is_allocated(self, site, owner):
        sale = build(site, owner, [line(stocked(site))])
        assert sale.reference.startswith("FA-")
        assert sale.reference.endswith("-0001")

    def test_consecutive_sales_increment(self, site, owner):
        first = build(site, owner, [line(stocked(site))])
        second = build(site, owner, [line(stocked(site))])
        assert (
            int(second.reference.split("-")[-1])
            == int(first.reference.split("-")[-1]) + 1
        )

    def test_the_invoice_sequence_is_separate_from_transactions(self, site, owner):
        build(site, owner, [line(stocked(site))])
        assert DocumentSequence.objects.get(prefix="FA").last_number == 1
        assert not DocumentSequence.objects.filter(prefix="TR").exists()

    def test_a_new_sale_is_completed(self, site, owner):
        assert build(site, owner, [line(stocked(site))]).status == "COMPLETED"

    def test_the_user_name_is_snapshotted(self, site, owner):
        assert build(site, owner, [line(stocked(site))]).user_name == owner.full_name


class TestBillingSnapshot:
    def test_the_customer_block_is_captured(self, site, owner):
        customer = CustomerFactory(
            name="Kivu Market", address="10 av. du Lac", tax_number="A123"
        )
        sale = build(site, owner, [line(stocked(site))], customer=customer)

        assert sale.customer == customer
        assert sale.customer_name == "Kivu Market"
        assert sale.customer_address == "10 av. du Lac"
        assert sale.customer_tax_number == "A123"

    def test_a_walk_in_sale_has_no_customer(self, site, owner):
        sale = build(site, owner, [line(stocked(site))])
        assert sale.customer is None
        assert sale.customer_name is None


class TestLineSnapshots:
    def test_every_field_is_frozen_at_sale_time(self, site, owner):
        article = stocked(
            site,
            name="Sucre",
            sku="EPI-1",
            purchase_price=800,
            vat_rate=Decimal("16.00"),
        )
        sale = build(site, owner, [line(article, quantity=3, unit_price=1_200)])

        row = sale.lines.get()
        assert row.article_name == "Sucre"
        assert row.article_sku == "EPI-1"
        assert row.unit == article.unit
        assert row.quantity == 3
        assert row.unit_price == 1_200
        assert row.unit_cost == 800
        assert row.vat_rate == Decimal("16.00")

    def test_the_snapshot_survives_a_later_reprice(self, site, owner):
        article = stocked(site, purchase_price=800)
        sale = build(site, owner, [line(article)])

        article.purchase_price = 9_999
        article.save()

        assert sale.lines.get().unit_cost == 800

    def test_the_unit_price_may_be_negotiated_below_the_article_price(
        self, site, owner
    ):
        article = stocked(site, sale_price=5_000)
        sale = build(site, owner, [line(article, unit_price=4_000)])
        assert sale.lines.get().unit_price == 4_000


class TestTotals:
    def test_they_match_the_arithmetic_module(self, site, owner):
        from apps.sales.totals import LineInput, compute_sale_totals

        first = stocked(site, vat_rate=Decimal("16.00"))
        second = stocked(site, vat_rate=Decimal("5.50"))

        sale = build(
            site,
            owner,
            [line(first, 3, 1_200), line(second, 1, 4_000)],
            discount=500,
        )

        expected = compute_sale_totals(
            [
                LineInput(quantity=3, unit_price=1_200, vat_rate=Decimal("16.00")),
                LineInput(quantity=1, unit_price=4_000, vat_rate=Decimal("5.50")),
            ],
            discount=500,
        )

        assert sale.subtotal == expected.subtotal
        assert sale.discount == expected.discount
        assert sale.total == expected.total
        assert sale.vat_total == expected.vat_total

    def test_the_discount_shares_are_persisted_per_line(self, site, owner):
        sale = build(
            site,
            owner,
            [line(stocked(site), 1, 1_000), line(stocked(site), 1, 1_000)],
            discount=100,
        )
        shares = sorted(row.discount_share for row in sale.lines.all())
        assert sum(shares) == 100

    def test_the_discount_rate_is_recorded_but_not_used(self, site, owner):
        """It exists so the UI can redisplay '10 %'. `discount` is
        authoritative."""
        sale = build(
            site,
            owner,
            [line(stocked(site), 1, 10_000)],
            discount=1_000,
            discount_rate=Decimal("10.00"),
        )
        assert sale.discount == 1_000
        assert sale.discount_rate == Decimal("10.00")
        assert sale.total == 9_000


class TestStock:
    def test_one_out_sale_movement_per_line(self, site, owner):
        first, second = stocked(site), stocked(site)
        sale = build(site, owner, [line(first, 2), line(second, 3)])

        movements = list(sale.movements.all())
        assert len(movements) == 2
        assert {m.type for m in movements} == {"OUT"}
        assert {m.reason for m in movements} == {"SALE"}

    def test_stock_falls_by_the_sold_quantity(self, site, owner):
        article = stocked(site, quantity=50)
        build(site, owner, [line(article, quantity=8)])
        assert StockLevel.objects.get(article=article).quantity == 42

    def test_the_movement_carries_the_sale_reference(self, site, owner):
        sale = build(site, owner, [line(stocked(site))])
        assert sale.movements.get().reference == sale.reference

    def test_the_movement_carries_no_unit_cost(self, site, owner):
        """`createSale` passes unitCost: null — a sale's cost is on the line
        snapshot, not the movement."""
        sale = build(site, owner, [line(stocked(site))])
        assert sale.movements.get().unit_cost is None


class TestValidation:
    def test_a_line_exceeding_stock_names_its_row(self, site, owner):
        good, bad = stocked(site, quantity=100), stocked(site, quantity=1)

        with pytest.raises(ValidationError) as exc:
            build(site, owner, [line(good, 2), line(bad, 99)])

        assert "lines.1.quantity" in exc.value.detail

    def test_a_failed_sale_writes_nothing(self, site, owner):
        good, bad = stocked(site, quantity=100), stocked(site, quantity=1)

        with pytest.raises(ValidationError):
            build(site, owner, [line(good, 2), line(bad, 99)])

        assert Sale.objects.count() == 0
        assert SaleLine.objects.count() == 0
        assert StockMovement.objects.count() == 0
        assert StockLevel.objects.get(article=good).quantity == 100

    def test_a_failed_sale_leaves_no_gap_in_the_invoice_sequence(self, site, owner):
        build(site, owner, [line(stocked(site))])
        bad = stocked(site, quantity=1)

        with pytest.raises(ValidationError):
            build(site, owner, [line(bad, 99)])

        assert build(site, owner, [line(stocked(site))]).reference.endswith("-0002")

    def test_a_discount_over_the_subtotal_is_rejected(self, site, owner):
        with pytest.raises(ValidationError) as exc:
            build(site, owner, [line(stocked(site), 1, 1_000)], discount=1_001)

        assert exc.value.detail["discount"][0] == (
            "La remise ne peut pas dépasser le total de la vente."
        )

    def test_a_discount_equal_to_the_subtotal_is_allowed(self, site, owner):
        sale = build(site, owner, [line(stocked(site), 1, 1_000)], discount=1_000)
        assert sale.total == 0
