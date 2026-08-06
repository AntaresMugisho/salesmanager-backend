"""Money primitives.

`round_half_up` exists because Python's `round()` is banker's rounding and
JavaScript's `Math.round` is half-up. The frontend computes what a sale is
worth; a divergence here is a wrong number on an invoice.
"""

from datetime import date, datetime, timezone as dt_timezone

import pytest
from django.test import override_settings

from apps.common.dates import at_local_noon
from apps.common.money import format_cents, round_half_up


class TestRoundHalfUp:
    @pytest.mark.parametrize(
        ("numerator", "denominator", "expected"),
        [
            (1, 2, 1),  # 0.5  -> 1   (Python's round() gives 0)
            (3, 2, 2),  # 1.5  -> 2
            (5, 2, 3),  # 2.5  -> 3   (Python's round() gives 2)
            (7, 2, 4),  # 3.5  -> 4
            (1, 3, 0),  # 0.33 -> 0
            (2, 3, 1),  # 0.67 -> 1
            (0, 7, 0),
            (7, 7, 1),
        ],
    )
    def test_matches_javascript_math_round(self, numerator, denominator, expected):
        assert round_half_up(numerator, denominator) == expected

    def test_the_half_cases_are_where_python_round_would_disagree(self):
        """Guard the reason this function exists. If someone 'simplifies' it
        to round(n / d), these two flip."""
        assert round_half_up(1, 2) == 1 and round(1 / 2) == 0
        assert round_half_up(5, 2) == 3 and round(5 / 2) == 2

    def test_a_real_vat_extraction(self):
        # taxable 1050 cents at 16% TTC -> 1050 * 1600 / 11600
        assert round_half_up(1050 * 1600, 10000 + 1600) == 145

    def test_it_is_exact_at_magnitudes_that_would_lose_float_precision(self):
        huge = 10**18
        assert round_half_up(2 * huge + 1, 2) == huge + 1

    def test_a_zero_denominator_is_a_programming_error(self):
        with pytest.raises(ValueError):
            round_half_up(1, 0)


class TestFormatCents:
    # Escapes rather than literal characters, deliberately: U+202F and U+00A0
    # are invisible in an editor and survive copy-paste badly. Spelled out,
    # they say which character is required.
    NARROW_NBSP = "\u202f"
    NBSP = "\u00a0"

    @pytest.mark.parametrize(
        ("cents", "expected"),
        [
            (123450, "1\u202f234,50\u00a0$US"),
            (500, "5,00\u00a0$US"),
            (0, "0,00\u00a0$US"),
            (1500, "15,00\u00a0$US"),
            (5, "0,05\u00a0$US"),
            (123456789, "1\u202f234\u202f567,89\u00a0$US"),
        ],
    )
    def test_matches_the_frontends_intl_output(self, cents, expected):
        """Verified against Intl.NumberFormat("fr-FR", {currency: "USD"}):
        U+202F narrow no-break space groups thousands, U+00A0 precedes $US."""
        assert format_cents(cents) == expected

    def test_the_separators_are_not_ordinary_spaces(self):
        """A plain space renders identically and compares unequal — exactly
        the sort of difference that only shows up in an assertion."""
        formatted = format_cents(123450)
        assert self.NARROW_NBSP in formatted
        assert f"{self.NBSP}$US" in formatted
        assert " " not in formatted


class TestAtLocalNoon:
    @override_settings(SHOP_TIME_ZONE="Africa/Kinshasa")
    def test_widens_a_bare_date_to_local_noon_in_utc(self):
        # Kinshasa is UTC+1, so local noon is 11:00 UTC.
        assert at_local_noon(date(2026, 7, 2)) == datetime(
            2026, 7, 2, 11, 0, tzinfo=dt_timezone.utc
        )

    @override_settings(SHOP_TIME_ZONE="Africa/Kinshasa")
    def test_noon_lands_on_the_picked_day_whatever_the_offset(self):
        """The whole point: midnight would be ambiguous across a timezone
        boundary, noon never is."""
        from apps.common.dates import end_of_day, start_of_day

        picked = date(2026, 7, 2)
        moment = at_local_noon(picked)
        assert start_of_day(picked) < moment < end_of_day(picked)

    @override_settings(SHOP_TIME_ZONE="UTC")
    def test_a_utc_shop_gets_utc_noon(self):
        assert at_local_noon(date(2026, 7, 2)) == datetime(
            2026, 7, 2, 12, 0, tzinfo=dt_timezone.utc
        )
