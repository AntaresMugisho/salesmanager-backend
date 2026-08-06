"""Money primitives shared by the sales and finance sub-projects.

Everything here is integer cents. No floats, anywhere.
"""


def round_half_up(numerator: int, denominator: int) -> int:
    """Round `numerator / denominator` half away from the lower value.

    This is JavaScript's `Math.round`, which the frontend's
    `features/sales/lib/totals.ts` uses for every rounded figure on a sale.
    Python's built-in `round()` is banker's rounding: `Math.round(2.5)` is 3
    while `round(2.5)` is 2, and integer-cent discount allocation lands on
    exact halves routinely. That one cent would appear on an invoice.

    Implemented as exact integer arithmetic rather than `round(n / d)` or
    `Decimal`, so there is no float in the path at all: adding half a unit
    before flooring is `(2n + d) // 2d`. Floor division on a negative operand
    rounds toward negative infinity, which is also what `Math.round(-2.5) ->
    -2` does, so the identity holds for negatives too — though every value in
    this codebase is non-negative.
    """
    if denominator <= 0:
        raise ValueError("denominator must be positive")
    return (2 * numerator + denominator) // (2 * denominator)


def format_cents(cents: int) -> str:
    """Cents to the frontend's money string: `1 234,50 $US`.

    Matches `formatMoney` in `lib/format.ts`, which is
    `Intl.NumberFormat("fr-FR", {style: "currency", currency: "USD"})`.
    Reproduced by hand rather than with `locale` or `babel`: the exact
    separators matter and process-wide locale state does not belong in a
    formatting helper.

    The two spacing characters are not ordinary spaces — U+202F (narrow
    no-break) groups thousands and U+00A0 (no-break) precedes the symbol.
    """
    sign = "-" if cents < 0 else ""
    whole, fraction = divmod(abs(cents), 100)
    grouped = f"{whole:,}".replace(",", " ")
    return f"{sign}{grouped},{fraction:02d} $US"
