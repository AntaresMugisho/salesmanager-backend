"""Calendar-date bounds.

Africa/Kinshasa is UTC+1 with no DST, so local midnight is 23:00 UTC on the
previous day. Every assertion below turns on that one hour: a UTC
implementation passes none of them.
"""

from datetime import date, datetime, timezone as dt_timezone

from django.test import override_settings

from apps.common.dates import end_of_day, start_of_day, today_start


@override_settings(SHOP_TIME_ZONE="Africa/Kinshasa")
def test_start_of_day_is_local_midnight_expressed_in_utc():
    assert start_of_day(date(2026, 7, 1)) == datetime(
        2026, 6, 30, 23, 0, 0, tzinfo=dt_timezone.utc
    )


@override_settings(SHOP_TIME_ZONE="Africa/Kinshasa")
def test_end_of_day_is_the_last_local_instant_expressed_in_utc():
    assert end_of_day(date(2026, 7, 31)) == datetime(
        2026, 7, 31, 22, 59, 59, 999999, tzinfo=dt_timezone.utc
    )


@override_settings(SHOP_TIME_ZONE="Africa/Kinshasa")
def test_the_bounds_of_one_day_do_not_overlap_the_next():
    assert end_of_day(date(2026, 7, 1)) < start_of_day(date(2026, 7, 2))


@override_settings(SHOP_TIME_ZONE="UTC")
def test_a_utc_shop_gets_utc_midnight():
    assert start_of_day(date(2026, 7, 1)) == datetime(
        2026, 7, 1, 0, 0, 0, tzinfo=dt_timezone.utc
    )


@override_settings(SHOP_TIME_ZONE="Africa/Kinshasa")
def test_today_start_uses_the_shop_day_not_the_utc_day():
    """At 23:30 UTC it is already tomorrow in Kinshasa.

    A UTC implementation returns today's UTC midnight and would count a
    movement made two minutes ago as belonging to a day that, locally, ended
    half an hour earlier.
    """
    from unittest import mock

    from django.utils import timezone as dj_timezone

    late = datetime(2026, 7, 1, 23, 30, tzinfo=dt_timezone.utc)
    with mock.patch.object(dj_timezone, "now", return_value=late):
        # Local date is 2026-07-02, whose midnight is 2026-07-01T23:00Z.
        assert today_start() == datetime(2026, 7, 1, 23, 0, 0, tzinfo=dt_timezone.utc)


def test_shop_time_zone_is_configured(settings):
    from zoneinfo import ZoneInfo

    assert ZoneInfo(settings.SHOP_TIME_ZONE) is not None
