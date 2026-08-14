"""The one canonical stock-status rule.

Both comparisons are inclusive, and both boundaries are tested: a quantity
exactly at the threshold is LOW, and zero is OUT_OF_STOCK even when the
threshold is zero too.
"""

from apps.common.tests.purity import django_imports_of
from apps.stock import status as status_module
from apps.stock.status import derive_stock_status


class TestDeriveStockStatus:
    def test_zero_is_out_of_stock(self):
        assert derive_stock_status(0, 5) == "OUT_OF_STOCK"

    def test_zero_is_out_of_stock_even_with_a_zero_threshold(self):
        assert derive_stock_status(0, 0) == "OUT_OF_STOCK"

    def test_at_the_threshold_is_low(self):
        assert derive_stock_status(5, 5) == "LOW"

    def test_below_the_threshold_is_low(self):
        assert derive_stock_status(1, 5) == "LOW"

    def test_above_the_threshold_is_in_stock(self):
        assert derive_stock_status(6, 5) == "IN_STOCK"

    def test_a_positive_quantity_with_a_zero_threshold_is_in_stock(self):
        assert derive_stock_status(1, 0) == "IN_STOCK"


class TestPurity:
    def test_the_module_does_not_import_django(self):
        assert django_imports_of(status_module) == []


class TestNegative:
    """Below zero is its own status.

    A level of 0 means "reorder". A level of -3 means the books recorded three
    units that were not there — an inventory correction, not a purchase. Both
    used to read OUT_OF_STOCK.
    """

    def test_below_zero_is_negative(self):
        assert derive_stock_status(-3, 5) == "NEGATIVE"

    def test_minus_one_is_negative(self):
        assert derive_stock_status(-1, 0) == "NEGATIVE"

    def test_zero_is_still_out_of_stock(self):
        assert derive_stock_status(0, 5) == "OUT_OF_STOCK"

    def test_the_threshold_does_not_affect_a_negative(self):
        assert derive_stock_status(-3, 0) == "NEGATIVE"
        assert derive_stock_status(-3, 100) == "NEGATIVE"

    def test_positive_levels_are_unaffected(self):
        assert derive_stock_status(3, 5) == "LOW"
        assert derive_stock_status(6, 5) == "IN_STOCK"
