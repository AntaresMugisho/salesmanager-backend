"""Local calendar dates.

`MovementListParams.dateFrom` / `dateTo` and `DashboardStats.movementsToday`
are local-calendar concepts. `services/stock.ts` says so explicitly: it parses
`"2026-07-01"` without a `Z` suffix precisely so the browser reads it as local
midnight.

Storage is UTC and `TIME_ZONE` is UTC. These three functions are the only
place `SHOP_TIME_ZONE` is used, so there is exactly one definition of where a
day begins.
"""

# datetime.UTC, not django.utils.timezone.utc — the Django alias was
# deprecated in 4.1 and removed in 5.0, and this project is on 6.0.
from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

from django.conf import settings
from django.utils import timezone


def shop_timezone() -> ZoneInfo:
    return ZoneInfo(settings.SHOP_TIME_ZONE)


def start_of_day(value: date) -> datetime:
    """Local midnight on `value`, as an aware UTC datetime."""
    local = datetime.combine(value, time.min, tzinfo=shop_timezone())
    return local.astimezone(UTC)


def end_of_day(value: date) -> datetime:
    """The last local instant of `value`, as an aware UTC datetime.

    23:59:59.999999 rather than the next midnight, because the frontend's
    `dateTo` is inclusive and a half-open upper bound would silently include
    the first microsecond of the following day.
    """
    local = datetime.combine(value, time.max, tzinfo=shop_timezone())
    return local.astimezone(UTC)


def today_start() -> datetime:
    """Local midnight of the shop's current day, as an aware UTC datetime."""
    return start_of_day(timezone.now().astimezone(shop_timezone()).date())
