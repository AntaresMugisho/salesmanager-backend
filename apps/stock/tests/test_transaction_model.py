"""StockTransaction invariants."""

import pytest
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError

from apps.catalogue.tests.factories import SupplierFactory
from apps.stock.models import StockMovement, StockTransaction
from apps.stock.tests.factories import StockMovementFactory, StockTransactionFactory

pytestmark = pytest.mark.django_db


class TestReference:
    def test_references_are_unique(self, site):
        StockTransactionFactory(reference="TR-2026-0001")
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                StockTransactionFactory(reference="TR-2026-0001")


class TestSupplier:
    def test_supplier_is_optional(self, site):
        assert StockTransactionFactory(supplier=None).supplier is None

    def test_a_supplier_with_transactions_cannot_be_deleted(self, site):
        supplier = SupplierFactory()
        StockTransactionFactory(supplier=supplier, supplier_name=supplier.name)
        with pytest.raises(ProtectedError):
            supplier.delete()

    def test_the_supplier_name_is_snapshotted(self, site):
        """A rename must not rewrite what last year's delivery note says."""
        supplier = SupplierFactory(name="Brasimba")
        header = StockTransactionFactory(supplier=supplier, supplier_name="Brasimba")

        supplier.name = "Brasimba SARL"
        supplier.save()
        header.refresh_from_db()

        assert header.supplier_name == "Brasimba"


class TestUser:
    def test_a_user_with_transactions_cannot_be_deleted(self, site, owner):
        StockTransactionFactory(user=owner, user_name=owner.full_name)
        with pytest.raises(ProtectedError):
            owner.delete()


class TestLines:
    def test_movements_reach_their_header_through_lines(self, site, owner):
        header = StockTransactionFactory(user=owner)
        first = StockMovementFactory(site=site, user=owner, transaction=header)
        second = StockMovementFactory(site=site, user=owner, transaction=header)
        StockMovementFactory(site=site, user=owner)  # standalone

        assert set(header.lines.all()) == {first, second}

    def test_a_standalone_movement_has_no_transaction(self, site, owner):
        assert StockMovementFactory(site=site, user=owner).transaction is None

    def test_a_transaction_with_lines_cannot_be_deleted(self, site, owner):
        """PROTECT never fires today because nothing deletes a transaction.
        It is the honest declaration of that, rather than a CASCADE that would
        quietly delete ledger rows if a delete path ever appeared."""
        header = StockTransactionFactory(user=owner)
        StockMovementFactory(site=site, user=owner, transaction=header)

        with pytest.raises(ProtectedError):
            header.delete()


class TestChoices:
    def test_type_and_reason_reuse_the_movement_choices(self):
        """A transaction whose choices could drift from its own lines' choices
        is a bug waiting to happen."""
        transaction_types = dict(StockTransaction._meta.get_field("type").choices)
        movement_types = dict(StockMovement._meta.get_field("type").choices)
        assert transaction_types == movement_types

        transaction_reasons = dict(StockTransaction._meta.get_field("reason").choices)
        movement_reasons = dict(StockMovement._meta.get_field("reason").choices)
        assert transaction_reasons == movement_reasons


class TestOrdering:
    def test_newest_first(self, site, owner):
        first = StockTransactionFactory(user=owner, reference="TR-2026-0001")
        second = StockTransactionFactory(user=owner, reference="TR-2026-0002")
        assert list(StockTransaction.objects.all()) == [second, first]
