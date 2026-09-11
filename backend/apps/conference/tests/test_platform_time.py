"""Пояс платформы — не пояс сервера (сервер хранит и считает в UTC).

Момент теста — 20:00 UTC: специально такой, где дата в UTC и в поясе
платформы (Asia/Almaty, UTC+5 по умолчанию) РАЗНАЯ. Тест на моменте, где
даты совпадают, прошёл бы и на сломанном коде (том самом, что вернул
``timezone.localtime()`` — тихое no-op без активного пояса).
"""

import datetime as dt

from apps.conference.services import platform_time

MOMENT_UTC = dt.datetime(2026, 8, 25, 20, 0, tzinfo=dt.timezone.utc)


def test_to_platform_shifts_into_the_next_day():
    local = platform_time.to_platform(MOMENT_UTC)

    assert local.date() == dt.date(2026, 8, 26)
    assert local.hour == 1
    assert local.utcoffset() == dt.timedelta(hours=5)


def test_today_follows_the_platform_date_not_utc():
    # В UTC на этот момент ещё 25-е; по местному времени платформы — уже 26-е.
    assert MOMENT_UTC.date() == dt.date(2026, 8, 25)
    assert platform_time.today(MOMENT_UTC) == dt.date(2026, 8, 26)


def test_utc_offset_label_follows_the_same_object_being_printed():
    local = platform_time.to_platform(MOMENT_UTC)

    assert platform_time.utc_offset_label(local) == "UTC+5"
