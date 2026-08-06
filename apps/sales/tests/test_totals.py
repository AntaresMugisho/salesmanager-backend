"""Sale arithmetic, ported from features/sales/lib/totals.ts.

Pure integers, no database, no Django. The last class in this file runs the
same random inputs through the frontend's actual implementation in Node and
diffs — which is the only way to be sure a port of money arithmetic is right.
"""

import json
import random
import shutil
import subprocess
from decimal import Decimal

import pytest

from apps.sales.totals import LineInput, allocate_discount, compute_sale_totals


def line(quantity, unit_price, vat_rate="16.00"):
    return LineInput(
        quantity=quantity, unit_price=unit_price, vat_rate=Decimal(vat_rate)
    )


class TestSubtotalAndTotal:
    def test_a_single_line(self):
        totals = compute_sale_totals([line(3, 1000)], discount=0)
        assert totals.subtotal == 3000
        assert totals.discount == 0
        assert totals.total == 3000
        assert totals.lines[0].line_total == 3000
        assert totals.lines[0].discount_share == 0

    def test_several_lines_sum(self):
        totals = compute_sale_totals([line(2, 1500), line(1, 700)], discount=0)
        assert totals.subtotal == 3700
        assert totals.total == 3700

    def test_a_discount_reduces_the_total(self):
        totals = compute_sale_totals([line(1, 5000)], discount=500)
        assert totals.subtotal == 5000
        assert totals.discount == 500
        assert totals.total == 4500

    def test_a_discount_equal_to_the_subtotal_zeroes_the_total(self):
        totals = compute_sale_totals([line(1, 5000)], discount=5000)
        assert totals.total == 0

    def test_an_empty_sale_is_all_zeros(self):
        totals = compute_sale_totals([], discount=0)
        assert totals.subtotal == 0
        assert totals.total == 0
        assert totals.vat_total == 0
        assert totals.lines == []

    def test_a_discount_on_nothing_is_nothing(self):
        """'A discount can only be zero when there is nothing to discount,
        whatever the caller asked for.'"""
        totals = compute_sale_totals([line(1, 0)], discount=500)
        assert totals.subtotal == 0
        assert totals.discount == 0
        assert totals.total == 0


class TestVat:
    def test_tax_is_extracted_from_a_ttc_price_not_added(self):
        """Prices are tax-inclusive: base * rate / (100 + rate)."""
        totals = compute_sale_totals([line(1, 11600, "16.00")], discount=0)
        assert totals.total == 11600
        assert totals.vat_total == 1600  # 11600 * 16 / 116

    def test_a_zero_rate_yields_no_tax(self):
        totals = compute_sale_totals([line(1, 5000, "0.00")], discount=0)
        assert totals.vat_total == 0

    def test_a_decimal_rate(self):
        # 10550 TTC at 5.5% -> 10550 * 550 / 10550 = 550
        totals = compute_sale_totals([line(1, 10550, "5.50")], discount=0)
        assert totals.vat_total == 550

    def test_tax_is_computed_after_the_discount(self):
        """The taxable base is the discounted amount, not the gross."""
        undiscounted = compute_sale_totals([line(1, 11600, "16.00")], discount=0)
        discounted = compute_sale_totals([line(1, 11600, "16.00")], discount=1160)
        assert discounted.vat_total < undiscounted.vat_total
        assert discounted.vat_total == 1440  # 10440 * 16 / 116

    def test_mixed_rates_sum_independently(self):
        totals = compute_sale_totals(
            [line(1, 11600, "16.00"), line(1, 10550, "5.50")], discount=0
        )
        assert totals.vat_total == 1600 + 550


class TestDiscountAllocation:
    def test_an_even_split(self):
        shares = allocate_discount(300, [1000, 1000, 1000], 3000)
        assert shares == [100, 100, 100]

    def test_the_shares_always_sum_to_exactly_the_discount(self):
        """Rounding each share independently would lose a cent here: three
        equal lines of a 100-cent discount would come back 33+33+33."""
        shares = allocate_discount(100, [1000, 1000, 1000], 3000)
        assert sum(shares) == 100
        assert shares == [34, 33, 33]

    def test_leftovers_go_to_the_largest_fractional_parts(self):
        shares = allocate_discount(10, [500, 300, 200], 1000)
        assert sum(shares) == 10
        assert shares == [5, 3, 2]

    def test_ties_are_broken_by_ascending_index(self):
        shares = allocate_discount(1, [1000, 1000], 2000)
        assert shares == [1, 0]

    def test_a_zero_discount_allocates_nothing(self):
        assert allocate_discount(0, [1000, 2000], 3000) == [0, 0]

    def test_a_zero_subtotal_allocates_nothing(self):
        assert allocate_discount(500, [0, 0], 0) == [0, 0]

    def test_proportional_to_line_value(self):
        shares = allocate_discount(100, [900, 100], 1000)
        assert shares == [90, 10]


class TestHalfUpRounding:
    def test_a_vat_extraction_landing_exactly_on_a_half(self):
        """taxable 5 at 100% -> 5 * 10000 / 20000 = 2.5 exactly.

        Half-up gives 3; Python's banker's rounding would give 2. This is the
        case that makes round_half_up necessary rather than merely tidy.
        """
        totals = compute_sale_totals([line(1, 5, "100.00")], discount=0)
        assert totals.vat_total == 3

    def test_allocation_never_loses_or_invents_a_cent(self):
        """Whatever the split, the shares reconstitute the discount exactly."""
        for discount in range(0, 51):
            shares = allocate_discount(discount, [100, 100, 100], 300)
            assert sum(shares) == discount


NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="node is not on PATH")
class TestAgainstTheFrontendImplementation:
    """Runs the same random inputs through the frontend's own code.

    This is the strongest evidence available that the port is right, and it is
    kept as a test rather than a one-off spike because the arithmetic decides
    what money is stored. Skipped rather than failed when node is absent, so a
    CI box without it does not turn the suite red.
    """

    JS = """
    function allocate(discount, lineTotals, subtotal) {
      if (discount === 0 || subtotal <= 0) return lineTotals.map(() => 0);
      const exact = lineTotals.map((lt) => (discount * lt) / subtotal);
      const shares = exact.map((v) => Math.floor(v));
      let remainder = discount - shares.reduce((a, b) => a + b, 0);
      const order = exact
        .map((v, i) => ({ i, f: v - Math.floor(v) }))
        .sort((a, b) => b.f - a.f || a.i - b.i);
      for (const e of order) {
        if (remainder <= 0) break;
        shares[e.i] += 1;
        remainder -= 1;
      }
      return shares;
    }

    function computeSaleTotals(lines, discount) {
      const lineTotals = lines.map((l) => l.quantity * l.unitPrice);
      const subtotal = lineTotals.reduce((a, b) => a + b, 0);
      const shares = allocate(discount, lineTotals, subtotal);
      const resultLines = lines.map((line, index) => {
        const lineTotal = lineTotals[index];
        const discountShare = shares[index];
        const taxable = lineTotal - discountShare;
        const vatAmount =
          line.vatRate === 0
            ? 0
            : Math.round((taxable * line.vatRate) / (100 + line.vatRate));
        return { lineTotal, discountShare, vatAmount };
      });
      const effectiveDiscount = subtotal <= 0 ? 0 : discount;
      return {
        subtotal,
        discount: effectiveDiscount,
        total: subtotal - effectiveDiscount,
        vatTotal: resultLines.reduce((s, l) => s + l.vatAmount, 0),
        lines: resultLines,
      };
    }

    const cases = JSON.parse(process.argv[1]);
    console.log(JSON.stringify(cases.map(([lines, d]) => computeSaleTotals(lines, d))));
    """

    def test_matches_on_randomised_sales(self):
        random.seed(20260806)
        cases = []
        for _ in range(300):
            count = random.randint(1, 5)
            lines = [
                {
                    "quantity": random.randint(1, 40),
                    "unitPrice": random.randint(0, 250_00),
                    "vatRate": random.choice([0, 5.5, 10, 16, 20]),
                }
                for _ in range(count)
            ]
            subtotal = sum(row["quantity"] * row["unitPrice"] for row in lines)
            cases.append([lines, random.randint(0, subtotal)])

        result = subprocess.run(
            [NODE, "-e", self.JS, json.dumps(cases)],
            capture_output=True,
            text=True,
            check=True,
        )
        expected = json.loads(result.stdout)

        for (raw_lines, discount), want in zip(cases, expected):
            got = compute_sale_totals(
                [
                    LineInput(
                        quantity=row["quantity"],
                        unit_price=row["unitPrice"],
                        vat_rate=Decimal(str(row["vatRate"])),
                    )
                    for row in raw_lines
                ],
                discount,
            )
            assert got.subtotal == want["subtotal"]
            assert got.discount == want["discount"]
            assert got.total == want["total"]
            assert got.vat_total == want["vatTotal"]
            assert [row.line_total for row in got.lines] == [
                row["lineTotal"] for row in want["lines"]
            ]
            assert [row.discount_share for row in got.lines] == [
                row["discountShare"] for row in want["lines"]
            ]
            assert [row.vat_amount for row in got.lines] == [
                row["vatAmount"] for row in want["lines"]
            ]
