"""Бизнес-метрики конференций.

Собирается ``apps.core.metrics.collect_all`` по расписанию (Celery-beat), не
на скрейпе — см. докстринг там. Обращается ТОЛЬКО к своим моделям:
кросс-доменные импорты запрещены (``apps/core/tests/test_app_isolation.py``).

Что здесь важно наблюдать. Запись конференции — конвейер из трёх звеньев
(SFU пишет → воркер сводит → воркер распознаёт), и ломается он молча: звонок
при этом идёт нормально, никто не жалуется, а записи просто не появляются.
Поэтому метрики целятся не в объём, а в застревание.
"""

from __future__ import annotations

import datetime as dt

from django.db.models import Count, Sum
from django.utils import timezone

from .models import (
    ConferenceRecording,
    ConferenceSession,
    RecordingKind,
    RecordingState,
    TranscriptState,
)


def collect() -> dict:
    now = timezone.now()
    day_ago = now - dt.timedelta(days=1)

    by_recording_state = (ConferenceSession.objects
                          .values("recording_state")
                          .annotate(n=Count("id")))

    stored_bytes = (ConferenceRecording.objects
                    .filter(kind=RecordingKind.COMPOSED)
                    .aggregate(total=Sum("size"))["total"]) or 0

    # Застрявшие: встреча кончилась больше часа назад, а запись всё ещё «в
    # обработке». Один такой — случайность, растущее число — воркер стоит.
    stuck_cutoff = now - dt.timedelta(hours=1)
    stuck = ConferenceSession.objects.filter(
        recording_state=RecordingState.PROCESSING,
        ended_at__lt=stuck_cutoff,
    ).count()

    pending_transcripts = ConferenceSession.objects.filter(
        transcript_state__in=(TranscriptState.PENDING, TranscriptState.PROCESSING),
        ended_at__isnull=False,
    ).count()

    return {
        "conference_sessions_by_recording_state": {
            "help": "Встречи по состоянию записи",
            "labels": ["state"],
            "values": [((row["recording_state"],), row["n"])
                       for row in by_recording_state],
        },
        "conference_sessions_last_day": {
            "help": "Встреч началось за последние сутки",
            "values": [((), ConferenceSession.objects
                        .filter(started_at__gte=day_ago).count())],
        },
        "conference_sessions_active": {
            "help": "Встречи, идущие прямо сейчас",
            "values": [((), ConferenceSession.objects
                        .filter(ended_at__isnull=True).count())],
        },
        "conference_recordings_stuck": {
            "help": "Записи, зависшие в обработке дольше часа после встречи",
            "values": [((), stuck)],
        },
        "conference_transcripts_pending": {
            "help": "Закончившиеся встречи, ожидающие расшифровки",
            "values": [((), pending_transcripts)],
        },
        "conference_storage_bytes": {
            "help": "Суммарный объём сведённых записей в хранилище",
            "values": [((), stored_bytes)],
        },
    }
