"""Перевод момента времени в пояс людей, а не сервера.

``TIME_ZONE`` Django — ``"UTC"``, и это правильно: хранение в UTC не зависит
от того, где сейчас стоит сервер, и не ловит проблем с переводом стрелок.
Но ``django.utils.timezone.localtime()`` конвертирует не в пояс людей, а в
**активный** пояс Django — а раз ``timezone.activate()`` нигде в проекте не
вызывается, активным остаётся тот же ``settings.TIME_ZONE``, то есть UTC.
Отсюда и был баг: ``timezone.localtime(...)`` тихо возвращал то же самое UTC
время, а рядом печаталась хардкоженная подпись «(UTC+5)» — значение и
подпись жили каждая своей жизнью и разъехались.

Здесь — единственное место, которое знает про ``settings.PLATFORM_TIME_ZONE``
(``Asia/Almaty`` по умолчанию, IANA-имя, а не число смещения: страна может
поменять закон о времени, и правка останется в одном месте). Оба потребителя
— письмо о старте встречи (``apps.conference.tasks``) и граница «сегодня» в
обзоре (``apps.conference.services.overview_service``) — обязаны брать пояс
отсюда, а не изобретать свой перевод.
"""

from __future__ import annotations

import datetime
from zoneinfo import ZoneInfo

from django.conf import settings


def _tz() -> ZoneInfo:
    return ZoneInfo(settings.PLATFORM_TIME_ZONE)


def to_platform(moment: datetime.datetime) -> datetime.datetime:
    """Момент (aware, любой пояс) — в поясе платформы.

    Обычный ``astimezone()``, а не ``timezone.localtime()`` — см. докстринг
    модуля: у Django нет активного пояса, отличного от UTC, и localtime()
    здесь бы просто вернул вход без изменений.
    """
    return moment.astimezone(_tz())


def utc_offset_label(local_moment: datetime.datetime) -> str:
    """«UTC+5» (или «UTC+5:30») для уже переведённого в пояс платформы момента.

    Считается ИЗ ``local_moment.utcoffset()``, а не хардкодом рядом с
    печатаемым временем — багом ревью и был как раз разъезд «время одно,
    подпись другая»: подпись обязана следовать из того же объекта времени,
    который печатается.
    """
    offset = local_moment.utcoffset()
    total_minutes = int(offset.total_seconds() // 60)
    sign = "+" if total_minutes >= 0 else "-"
    hours, minutes = divmod(abs(total_minutes), 60)
    if minutes:
        return f"UTC{sign}{hours}:{minutes:02d}"
    return f"UTC{sign}{hours}"


def today(moment: datetime.datetime | None = None) -> datetime.date:
    """Сегодняшняя дата в поясе платформы, а не сервера.

    Сервер хранит и считает в UTC, поэтому ``timezone.localdate()`` даёт
    дату UTC. Для встречи, начавшейся в 01:00 по Алматы (20:00 UTC
    накануне), это два разных календарных дня — граница суток обязана
    идти по местному, а не серверному времени.

    ``moment`` — точка отсчёта; по умолчанию «сейчас» (UTC). Явный параметр,
    а не только implicit ``datetime.now()`` внутри — тот же приём, что у
    ``session_service.finish_session(ended_at=None)``: тестам не нужно
    подменять системные часы, чтобы проверить перевод на известный момент.
    """
    moment = moment or datetime.datetime.now(datetime.timezone.utc)
    return to_platform(moment).date()
