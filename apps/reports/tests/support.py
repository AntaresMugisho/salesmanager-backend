"""Constants and helpers shared by the four report test modules.

A plain module, not a `conftest.py`: pytest can import a conftest under a
different module name than a direct import uses, which would give two copies of
these constants. There are no new fixtures here anyway — the root conftest
already provides `auth_client`, `site`, `owner`, `manager` and `cashier`.
"""

from datetime import date, datetime, timezone as dt_timezone
from zoneinfo import ZoneInfo

KINSHASA = ZoneInfo("Africa/Kinshasa")
JULY = (date(2026, 7, 1), date(2026, 7, 31))
PARAMS = {"from": "2026-07-01", "to": "2026-07-31"}
GENERATED_AT = datetime(2026, 8, 8, 9, 30, tzinfo=dt_timezone.utc)


def at(day, hour=12, month=7):
    """An instant inside the July range, in UTC."""
    return datetime(2026, month, day, hour, tzinfo=dt_timezone.utc)


def dated(model, instance, moment):
    """Force `created_at`, which `auto_now_add` sets on insert.

    The trap this exists to avoid: `SaleFactory(created_at=...)` is **silently
    ignored** — `auto_now_add` overwrites it during the insert and the test
    quietly runs against today's date instead of the period under test.

    Both `queryset.update()` and assigning the attribute then calling `save()`
    work after the insert, because `auto_now_add` only fires when `add=True`.
    This uses `update()` to match the existing idiom in
    `apps/finance/tests/test_finance_api.py` and
    `apps/sales/tests/test_sales_api.py`.
    """
    model.objects.filter(pk=instance.pk).update(created_at=moment)
    instance.refresh_from_db()
    return instance
