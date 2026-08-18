"""Публичный API аппки conference для ДРУГИХ аппок.

Единственный способ, которым сосед имеет право обращаться к conference.
Прямой импорт apps.conference.models / apps.conference.services из другой
аппки запрещён и ловится тестом apps/core/tests/test_app_isolation.py.

Каждая функция начинается с require_service("conference"): если аппка
выключена, вызывающий получит ServiceDisabled, который api_view превратит в
503-конверт (а не в 500) — см. htqweb/http.py.

Возвращаются только простые dict/списки, никогда ORM-объекты: сосед не
должен получить возможность править чужие строки напрямую.
"""

from apps.core.services import require_service

from apps.conference.models import ConferenceSession, RecordingState


def get_room_history(room_id: str, limit: int = 20) -> list[dict]:
    """Прошедшие встречи в комнате — от свежих к старым.

    Нужно календарю: у события с ``conference_room_id`` есть смысл показать
    «эта встреча уже проходила N раз, вот записи».
    """
    require_service("conference")
    rows = (ConferenceSession.objects
            .filter(room_id=room_id)
            .order_by("-started_at")[:limit]
            .values("id", "title", "started_at", "ended_at", "duration_sec",
                    "created_by_id", "created_by_name", "recording_state"))
    return [dict(row) for row in rows]


def get_session_summary(session_id: int) -> dict | None:
    """Краткая карточка встречи без проверки прав.

    ⚠️ Прав НЕ проверяет — их проверяет вызывающая аппка по своим правилам.
    Поэтому здесь только те поля, которые не раскрывают содержание встречи:
    ни протокола, ни ссылки на запись.
    """
    require_service("conference")
    session = (ConferenceSession.objects
               .filter(pk=session_id)
               .values("id", "room_id", "title", "started_at", "ended_at",
                       "duration_sec", "peak_participants", "recording_state",
                       "transcript_state", "expires_at")
               .first())
    return dict(session) if session else None


def has_recording(session_id: int) -> bool:
    """Есть ли у встречи готовая к просмотру запись."""
    require_service("conference")
    return ConferenceSession.objects.filter(
        pk=session_id, recording_state=RecordingState.READY,
    ).exists()
