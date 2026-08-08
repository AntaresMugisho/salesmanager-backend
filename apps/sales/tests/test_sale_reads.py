"""Derived figures: paidAmount, balance, paymentStatus, lineCount."""

import pytest

from apps.sales.querysets import sale_queryset
from apps.sales.tests.factories import PaymentFactory, SaleFactory, SaleLineFactory

pytestmark = pytest.mark.django_db


class TestAnnotations:
    def test_paid_amount_sums_the_payments(self, site, owner):
        sale = SaleFactory(user=owner, site=site, total=10_000)
        PaymentFactory(sale=sale, user=owner, amount=3_000)
        PaymentFactory(sale=sale, user=owner, amount=2_000)

        assert sale_queryset().get(pk=sale.pk).paid_amount == 5_000

    def test_paid_amount_is_zero_with_no_payments(self, site, owner):
        sale = SaleFactory(user=owner, site=site)
        assert sale_queryset().get(pk=sale.pk).paid_amount == 0

    def test_line_count_counts_the_lines(self, site, owner):
        sale = SaleFactory(user=owner, site=site)
        SaleLineFactory(sale=sale)
        SaleLineFactory(sale=sale)
        SaleLineFactory(sale=sale)

        assert sale_queryset().get(pk=sale.pk).line_count == 3

    def test_lines_and_payments_do_not_multiply_each_other(self, site, owner):
        """The bug this queryset is shaped to avoid.

        Annotating Count("lines") and Sum("payments__amount") together joins
        both tables, giving 3 x 2 = 6 rows: line_count would read 6 and
        paid_amount would read 3x its true value.
        """
        sale = SaleFactory(user=owner, site=site, total=10_000)
        for _ in range(3):
            SaleLineFactory(sale=sale)
        PaymentFactory(sale=sale, user=owner, amount=1_000)
        PaymentFactory(sale=sale, user=owner, amount=2_000)

        annotated = sale_queryset().get(pk=sale.pk)

        assert annotated.line_count == 3
        assert annotated.paid_amount == 3_000

    def test_annotations_are_per_sale_not_global(self, site, owner):
        first = SaleFactory(user=owner, site=site)
        second = SaleFactory(user=owner, site=site)
        PaymentFactory(sale=first, user=owner, amount=1_000)
        PaymentFactory(sale=second, user=owner, amount=7_000)

        by_id = {row.id: row for row in sale_queryset()}
        assert by_id[first.id].paid_amount == 1_000
        assert by_id[second.id].paid_amount == 7_000


class TestOrdering:
    """Regression guard for a bug the annotation introduces.

    Django drops `Meta.ordering` from any query carrying a GROUP BY, and
    `Count("lines")` introduces one. Without an explicit `order_by` the sale
    list comes back in arbitrary order and pagination can drop or repeat rows
    between pages — DRF only warns (`UnorderedObjectListWarning`) and carries
    on serving wrong pages.

    `CategoryViewSet` has the same GROUP BY and escapes it only because
    `CatalogueViewSet` gives it an OrderingFilter and an explicit `ordering`.
    `SaleViewSet` has neither, so the queryset must order itself.
    """

    def test_the_queryset_carries_an_explicit_order_by(self, site, owner):
        assert "ORDER BY" in str(sale_queryset().query)

    def test_newest_first(self, site, owner):
        from datetime import datetime, timezone as dt_timezone

        from apps.sales.models import Sale

        older = SaleFactory(user=owner, site=site, reference="FA-2026-0001")
        newer = SaleFactory(user=owner, site=site, reference="FA-2026-0002")
        # Set the timestamps explicitly rather than relying on two auto_now_add
        # values landing microseconds apart: the point is the ordering, not the
        # clock.
        Sale.objects.filter(pk=older.pk).update(
            created_at=datetime(2026, 7, 1, tzinfo=dt_timezone.utc)
        )
        Sale.objects.filter(pk=newer.pk).update(
            created_at=datetime(2026, 7, 2, tzinfo=dt_timezone.utc)
        )

        assert [row.id for row in sale_queryset()] == [newer.id, older.id]
