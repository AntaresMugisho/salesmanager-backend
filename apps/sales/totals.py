"""Sale money arithmetic, ported from features/sales/lib/totals.ts.

No Django imports, no database, no floats. Pure integer cents.

The frontend shares this logic between the sale form's live footer and the
service that persists the sale, precisely so the displayed total and the
stored total cannot differ. The backend now owns the persisting half, so this
module must agree with the frontend to the cent — see
`tests/test_totals.py::TestAgainstTheFrontendImplementation`, which checks
that against the frontend's actual code.
"""

from dataclasses import dataclass
from decimal import Decimal

from apps.common.money import round_half_up


@dataclass(frozen=True)
class LineInput:
    quantity: int
    #: Tax-inclusive (TTC), in cents.
    unit_price: int
    #: Percent, e.g. Decimal("16.00") — the rate embedded in `unit_price`.
    vat_rate: Decimal


@dataclass(frozen=True)
class LineResult:
    line_total: int
    discount_share: int
    vat_amount: int


@dataclass(frozen=True)
class SaleTotals:
    subtotal: int
    discount: int
    total: int
    #: Included in `total`, never added to it. Displayed as « dont TVA ».
    vat_total: int
    lines: list[LineResult]


def allocate_discount(
    discount: int, line_totals: list[int], subtotal: int
) -> list[int]:
    """Spread a global discount across lines in proportion to their value.

    Largest-remainder method: floor every exact share, then hand the leftover
    cents one at a time to the largest fractional parts, ties broken by
    ascending line index.

    The shares therefore sum to exactly `discount`. Rounding each share
    independently would not — three lines of a 100-cent discount would come
    back as 33+33+33 and quietly lose a cent, which then shows up as a VAT
    total that disagrees with the invoice.

    Every comparison is integer: the exact share is
    `discount * line / subtotal`, so its floor is integer division and its
    fractional part is ordered by the remainder. No float is constructed, so
    no two shares can compare equal by accident.
    """
    if discount == 0 or subtotal <= 0:
        return [0] * len(line_totals)

    shares = [(discount * line_total) // subtotal for line_total in line_totals]
    remainder = discount - sum(shares)

    # Each fractional part is < 1, so the remainder is always < the line count:
    # one pass over the ordering is enough, and no line is bumped twice.
    by_largest_fraction = sorted(
        range(len(line_totals)),
        key=lambda index: (-((discount * line_totals[index]) % subtotal), index),
    )

    for index in by_largest_fraction:
        if remainder <= 0:
            break
        shares[index] += 1
        remainder -= 1

    return shares


def compute_sale_totals(lines: list[LineInput], discount: int) -> SaleTotals:
    """`discount` is already resolved to cents by the caller.

    `SaleCreateDto` carries cents — the form resolves a percentage before
    sending — so the frontend's `resolveDiscountAmount` has no counterpart
    here.
    """
    line_totals = [line.quantity * line.unit_price for line in lines]
    subtotal = sum(line_totals)

    shares = allocate_discount(discount, line_totals, subtotal)

    result_lines: list[LineResult] = []
    for index, line in enumerate(lines):
        line_total = line_totals[index]
        discount_share = shares[index]
        taxable = line_total - discount_share

        # Prices are TTC, so the tax is extracted from the discounted amount
        # rather than added on top: base * rate / (100 + rate). The rate is
        # scaled by 100 to keep the arithmetic integral — the column is
        # DecimalField(5, 2), so 5.5 becomes 550 and taxable*550/10550 is
        # exactly taxable*5.5/105.5.
        rate_scaled = int(line.vat_rate * 100)
        vat_amount = (
            0
            if rate_scaled == 0
            else round_half_up(taxable * rate_scaled, 10000 + rate_scaled)
        )

        result_lines.append(
            LineResult(
                line_total=line_total,
                discount_share=discount_share,
                vat_amount=vat_amount,
            )
        )

    # A discount can only be zero when there is nothing to discount, whatever
    # the caller asked for.
    effective_discount = 0 if subtotal <= 0 else discount

    return SaleTotals(
        subtotal=subtotal,
        discount=effective_discount,
        total=subtotal - effective_discount,
        vat_total=sum(line.vat_amount for line in result_lines),
        lines=result_lines,
    )
