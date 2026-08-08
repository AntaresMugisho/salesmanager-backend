"""Period arithmetic, ported from features/finance/lib/period.ts.

Imports nothing from Django — deliberately. That isolation is what lets this
be compared against the frontend's own implementation without a database, and
a test asserts it.

Timezone-dependent functions take an explicit `tzinfo` rather than reading
settings, for the same reason. The caller passes
`apps.common.dates.shop_timezone()`.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta, tzinfo

#: Transcribed from `Intl.DateTimeFormat("fr-FR", {month: "short"})`, which is
#: what `features/finance/lib/period.ts` uses.
#:
#: Django's own French locale is NOT equivalent: it gives "jan." and "fév."
#: where CLDR gives "janv." and "févr.", so using `date_filter(d, "N")` would
#: mislabel two months on every chart.
#:
#: Note that four entries carry no trailing full stop — mars, mai, juin and
#: août are not abbreviated, and CLDR marks only abbreviations. Generating
#: these from a prefix would be wrong for half the year.
MONTH_ABBREVIATIONS: tuple[str, ...] = (
    "janv.",
    "févr.",
    "mars",
    "avr.",
    "mai",
    "juin",
    "juil.",
    "août",
    "sept.",
    "oct.",
    "nov.",
    "déc.",
)

#: Longest range still bucketed by day. Beyond it a year would draw 365 bars.
DAILY_BUCKET_LIMIT = 90


@dataclass(frozen=True)
class BucketSlot:
    key: str
    label: str


def days_in_range(start: date, end: date) -> int:
    """Inclusive day count.

    `date` arithmetic is calendar arithmetic, so unlike the frontend — which
    has to route through `Date.UTC` to stop a daylight-saving transition making
    a day 23 hours long — this needs no special handling.
    """
    return (end - start).days + 1


def resolve_granularity(start: date, end: date) -> str:
    return "DAY" if days_in_range(start, end) <= DAILY_BUCKET_LIMIT else "MONTH"


def day_label(value: date) -> str:
    """« 12 juil. » — the day is not zero-padded (`Intl` uses "numeric")."""
    return f"{value.day} {MONTH_ABBREVIATIONS[value.month - 1]}"


def month_label(value: date) -> str:
    """« juil. 2026 »."""
    return f"{MONTH_ABBREVIATIONS[value.month - 1]} {value.year}"


def local_date(moment: datetime, tz: tzinfo) -> date:
    """The calendar day this instant falls on, where the shop is.

    Every boundary in this module is a local calendar boundary, because that
    is the one the shopkeeper picked in the date input.
    """
    return moment.astimezone(tz).date()


def bucket_key(moment: datetime, tz: tzinfo, granularity: str) -> str:
    day = local_date(moment, tz)
    return day.isoformat() if granularity == "DAY" else day.strftime("%Y-%m")


def enumerate_buckets(start: date, end: date, granularity: str) -> list[BucketSlot]:
    """Every bucket in the range, empty ones included.

    A quiet week must render as zeros; dropping it would compress the x-axis
    and make the chart claim the shop traded on days it was shut.
    """
    slots: list[BucketSlot] = []

    if granularity == "DAY":
        cursor = start
        while cursor <= end:
            slots.append(BucketSlot(key=cursor.isoformat(), label=day_label(cursor)))
            cursor += timedelta(days=1)
        return slots

    cursor = start.replace(day=1)
    last = end.replace(day=1)
    while cursor <= last:
        slots.append(BucketSlot(key=cursor.strftime("%Y-%m"), label=month_label(cursor)))
        # `replace` cannot add a month, and adding 31 days can skip February.
        # Going to the 28th of this month and adding four days always lands in
        # the next one, whatever its length; snapping back to the 1st squares
        # it up.
        cursor = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
    return slots


def in_range(moment: datetime, tz: tzinfo, start: date, end: date) -> bool:
    """Both bounds inclusive.

    Compares calendar days rather than instants: the range's bounds are days,
    so "is this instant before the end" is the wrong question — the right one
    is "is this instant's local day within the span of days", which has no time
    component to get wrong.
    """
    return start <= local_date(moment, tz) <= end
