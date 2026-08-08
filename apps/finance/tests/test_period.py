"""Period arithmetic, ported from features/finance/lib/period.ts.

No Django, no database. The label test runs the frontend's own Intl call in
Node and diffs, because Django's French locale disagrees with it for two
months and the difference is invisible until it reaches a chart axis.
"""

import json
import shutil
import subprocess
from datetime import date, datetime, timezone as dt_timezone
from zoneinfo import ZoneInfo

import pytest

from apps.finance.period import (
    DAILY_BUCKET_LIMIT,
    MONTH_ABBREVIATIONS,
    bucket_key,
    day_label,
    days_in_range,
    enumerate_buckets,
    in_range,
    month_label,
    resolve_granularity,
)

KINSHASA = ZoneInfo("Africa/Kinshasa")


def django_imports_of(module) -> list[str]:
    """Every module this file imports whose root package is `django`.

    Parsed from the AST rather than grepped: the docstrings here talk about
    Django at length, and a substring search would flag the very comment
    explaining that there is no import.
    """
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(module))
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [a.name for a in node.names if a.name.split(".")[0] == "django"]
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if root == "django":
                found.append(node.module)
    return found


class TestNoDjangoImport:
    def test_the_module_does_not_import_django(self):
        """The isolation is the point: it is what lets this be diffed against
        the frontend's implementation without a database."""
        import apps.finance.period as module

        assert django_imports_of(module) == []


class TestDaysInRange:
    @pytest.mark.parametrize(
        ("start", "end", "expected"),
        [
            (date(2026, 7, 1), date(2026, 7, 1), 1),
            (date(2026, 7, 1), date(2026, 7, 2), 2),
            (date(2026, 7, 1), date(2026, 7, 31), 31),
            (date(2026, 1, 1), date(2026, 12, 31), 365),
            (date(2024, 1, 1), date(2024, 12, 31), 366),  # leap year
            (date(2026, 1, 31), date(2026, 2, 1), 2),  # month boundary
        ],
    )
    def test_the_count_is_inclusive(self, start, end, expected):
        assert days_in_range(start, end) == expected


class TestGranularity:
    def test_ninety_days_is_still_daily(self):
        """Verified against the frontend: 2026-01-01..2026-03-31 is 90 days."""
        assert days_in_range(date(2026, 1, 1), date(2026, 3, 31)) == 90
        assert resolve_granularity(date(2026, 1, 1), date(2026, 3, 31)) == "DAY"

    def test_ninety_one_days_switches_to_monthly(self):
        assert days_in_range(date(2026, 1, 1), date(2026, 4, 1)) == 91
        assert resolve_granularity(date(2026, 1, 1), date(2026, 4, 1)) == "MONTH"

    def test_the_limit_is_ninety(self):
        assert DAILY_BUCKET_LIMIT == 90

    def test_a_single_day_is_daily(self):
        assert resolve_granularity(date(2026, 7, 1), date(2026, 7, 1)) == "DAY"


class TestLabels:
    def test_there_are_twelve_abbreviations(self):
        assert len(MONTH_ABBREVIATIONS) == 12

    def test_four_months_take_no_trailing_period(self):
        """CLDR gives a full stop only to an actually-abbreviated form. mars,
        mai, juin and août are written out, so they get none — which is why
        this table is transcribed rather than generated from a prefix."""
        without = [m for m in MONTH_ABBREVIATIONS if not m.endswith(".")]
        assert without == ["mars", "mai", "juin", "août"]

    def test_a_day_label(self):
        assert day_label(date(2026, 7, 12)) == "12 juil."

    def test_a_day_label_is_not_zero_padded(self):
        """Intl uses day: "numeric", not "2-digit"."""
        assert day_label(date(2026, 7, 2)) == "2 juil."

    def test_a_month_label(self):
        assert month_label(date(2026, 7, 12)) == "juil. 2026"

    def test_january_and_february_are_the_ones_django_gets_wrong(self):
        """Django's French locale gives 'jan.' and 'fév.'. The contract needs
        'janv.' and 'févr.'."""
        assert day_label(date(2026, 1, 12)) == "12 janv."
        assert day_label(date(2026, 2, 12)) == "12 févr."


NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="node is not on PATH")
class TestLabelsAgainstIntl:
    """The table is a transcription, so a test that only restates it proves
    nothing. This one asks the frontend's own formatter."""

    JS = """
    const day = new Intl.DateTimeFormat("fr-FR", {day: "numeric", month: "short"});
    const mon = new Intl.DateTimeFormat("fr-FR", {month: "short", year: "numeric"});
    const out = [];
    for (let m = 0; m < 12; m++) {
      const d = new Date(2026, m, 12);
      out.push([day.format(d), mon.format(d)]);
    }
    console.log(JSON.stringify(out));
    """

    def test_all_twelve_match_the_frontends_intl_output(self):
        result = subprocess.run(
            [NODE, "-e", self.JS], capture_output=True, text=True, check=True
        )
        expected = json.loads(result.stdout)

        for index, (want_day, want_month) in enumerate(expected):
            value = date(2026, index + 1, 12)
            assert day_label(value) == want_day
            assert month_label(value) == want_month


class TestBucketKey:
    def test_a_day_key_is_the_local_calendar_date(self):
        # 23:30 UTC on 1 July is 00:30 on 2 July in Kinshasa (UTC+1).
        moment = datetime(2026, 7, 1, 23, 30, tzinfo=dt_timezone.utc)
        assert bucket_key(moment, KINSHASA, "DAY") == "2026-07-02"

    def test_a_month_key_truncates_the_day(self):
        moment = datetime(2026, 7, 12, 10, 0, tzinfo=dt_timezone.utc)
        assert bucket_key(moment, KINSHASA, "MONTH") == "2026-07"

    def test_the_timezone_can_move_a_key_across_a_month_boundary(self):
        """23:30 UTC on 31 July is 1 August locally."""
        moment = datetime(2026, 7, 31, 23, 30, tzinfo=dt_timezone.utc)
        assert bucket_key(moment, KINSHASA, "MONTH") == "2026-08"


class TestEnumerateBuckets:
    def test_daily_buckets_cover_every_day_inclusive(self):
        slots = enumerate_buckets(date(2026, 7, 1), date(2026, 7, 3), "DAY")
        assert [s.key for s in slots] == ["2026-07-01", "2026-07-02", "2026-07-03"]
        assert [s.label for s in slots] == ["1 juil.", "2 juil.", "3 juil."]

    def test_empty_buckets_are_emitted(self):
        """'A quiet week must render as zeros; dropping it would compress the
        x-axis and make the chart claim the shop traded on days it was shut.'
        Enumeration does not know what has data — that is the point."""
        assert len(enumerate_buckets(date(2026, 7, 1), date(2026, 7, 31), "DAY")) == 31

    def test_monthly_buckets_start_at_the_months_of_the_bounds(self):
        slots = enumerate_buckets(date(2026, 7, 15), date(2026, 9, 3), "MONTH")
        assert [s.key for s in slots] == ["2026-07", "2026-08", "2026-09"]
        assert [s.label for s in slots] == ["juil. 2026", "août 2026", "sept. 2026"]

    def test_monthly_buckets_cross_a_year_boundary(self):
        slots = enumerate_buckets(date(2026, 11, 1), date(2027, 1, 31), "MONTH")
        assert [s.key for s in slots] == ["2026-11", "2026-12", "2027-01"]

    def test_monthly_enumeration_survives_february(self):
        """The cursor advances by snapping to the 28th and adding four days;
        adding 31 would skip February entirely."""
        slots = enumerate_buckets(date(2026, 1, 1), date(2026, 4, 30), "MONTH")
        assert [s.key for s in slots] == ["2026-01", "2026-02", "2026-03", "2026-04"]

    def test_a_single_day_yields_one_bucket(self):
        assert len(enumerate_buckets(date(2026, 7, 1), date(2026, 7, 1), "DAY")) == 1


class TestInRange:
    def test_both_bounds_are_inclusive(self):
        start, end = date(2026, 7, 1), date(2026, 7, 31)
        first = datetime(2026, 7, 1, 6, 0, tzinfo=dt_timezone.utc)
        last = datetime(2026, 7, 31, 20, 0, tzinfo=dt_timezone.utc)

        assert in_range(first, KINSHASA, start, end)
        assert in_range(last, KINSHASA, start, end)

    def test_membership_is_a_calendar_day_comparison(self):
        """23:30 UTC on 30 June is already 1 July in Kinshasa, so it is in a
        July range even though its UTC date is not."""
        moment = datetime(2026, 6, 30, 23, 30, tzinfo=dt_timezone.utc)
        assert in_range(moment, KINSHASA, date(2026, 7, 1), date(2026, 7, 31))

    def test_outside_is_outside(self):
        moment = datetime(2026, 8, 1, 12, 0, tzinfo=dt_timezone.utc)
        assert not in_range(moment, KINSHASA, date(2026, 7, 1), date(2026, 7, 31))
