"""Ретенция 25 дней и сборка протокола.

Два обещания, данных пользователю, и оба легко нарушить незаметно:

* через 25 дней видео исчезает БЕЗВОЗВРАТНО, но история встречи и текстовый
  протокол остаются (решение заказчика);
* реплики протокола подписаны верным человеком и стоят на верной минуте.
  Ошибка в сдвиге тайм-кодов не уронит ничего — она просто сделает протокол
  тихо неправильным.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.conference import tasks
from apps.conference.models import (
    ConferenceParticipant,
    ConferenceRecording,
    ConferenceSession,
    ConferenceTranscriptSegment,
    RecordingKind,
    RecordingState,
    TranscriptState,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def expired_session(session):
    session.expires_at = timezone.now() - timedelta(days=1)
    session.save(update_fields=["expires_at"])
    ConferenceRecording.objects.create(
        session=session, kind=RecordingKind.COMPOSED,
        storage_path="conference/sessions/2026/07/1/recording.mp4",
        size=10_000_000, mime="video/mp4",
    )
    ConferenceRecording.objects.create(
        session=session, kind=RecordingKind.POSTER,
        storage_path="conference/sessions/2026/07/1/poster.jpg",
        size=40_000, mime="image/jpeg",
    )
    ConferenceTranscriptSegment.objects.create(
        session=session, speaker_name="Иванов", start_ms=1000, end_ms=4000,
        text="Начинаем планёрку",
    )
    return session


def test_purge_deletes_media_but_keeps_the_protocol(expired_session, monkeypatch):
    deleted: list[str] = []
    monkeypatch.setattr(
        "apps.conference.services.storage_service.delete_many",
        lambda paths: deleted.extend(paths) or len(deleted),
    )

    assert tasks.purge_expired() == 1

    assert sorted(deleted) == [
        "conference/sessions/2026/07/1/poster.jpg",
        "conference/sessions/2026/07/1/recording.mp4",
    ]
    expired_session.refresh_from_db()
    assert expired_session.recording_state == RecordingState.PURGED
    assert expired_session.purged_at is not None
    assert expired_session.recordings.count() == 0
    # Главное: встреча и её протокол на месте.
    assert ConferenceSession.objects.filter(pk=expired_session.pk).exists()
    assert expired_session.segments.count() == 1


def test_purge_is_idempotent(expired_session, monkeypatch):
    monkeypatch.setattr(
        "apps.conference.services.storage_service.delete_many", lambda paths: 0)
    assert tasks.purge_expired() == 1
    # Второй проход не должен находить ту же встречу снова: состояние
    # purged выведено из выборки, иначе уборщик каждую ночь дёргал бы
    # хранилище по уже удалённым ключам.
    assert tasks.purge_expired() == 0


def test_purge_spares_meetings_within_retention(session, monkeypatch):
    monkeypatch.setattr(
        "apps.conference.services.storage_service.delete_many", lambda paths: 0)
    ConferenceRecording.objects.create(
        session=session, kind=RecordingKind.COMPOSED,
        storage_path="keep.mp4", size=1, mime="video/mp4")

    assert tasks.purge_expired() == 0
    session.refresh_from_db()
    assert session.recording_state == RecordingState.READY


def test_retention_window_comes_from_settings(db, settings, organiser):
    from apps.conference.services import session_service

    settings.CONFERENCE_RETENTION_DAYS = 25
    started = timezone.now()
    created = session_service.start_session(
        room_id="r-ttl", started_at=started, created_by_id=organiser.pk)

    assert (created.expires_at - started).days == 25


# ── сборка протокола ───────────────────────────────────────────────────────

@pytest.fixture
def pending_session(session):
    """Встреча, ожидающая распознавания.

    Фикстура ``session`` описывает УЖЕ обработанную встречу
    (transcript_state=ready), а задача на такой штатно выходит сразу — это
    и защищает от повторного прогона. Тестам самого распознавания нужно
    исходное состояние.
    """
    session.transcript_state = TranscriptState.PENDING
    session.save(update_fields=["transcript_state"])
    return session


def test_transcript_merges_tracks_by_absolute_time(pending_session, monkeypatch):
    """Реплики двух участников выстраиваются в общий хронологический порядок.

    Whisper считает время от начала СВОЕЙ дорожки. Участник, вошедший на
    десятой минуте, дал файл, у которого нулевая секунда — это десятая минута
    встречи. Без сдвига на joined_offset_ms его реплики уехали бы в начало
    протокола.
    """
    early = ConferenceParticipant.objects.create(
        session=pending_session, display_name="Иванов", peer_id="p1",
        joined_at=pending_session.started_at, joined_offset_ms=0)
    late = ConferenceParticipant.objects.create(
        session=pending_session, display_name="Петров", peer_id="p2",
        joined_at=pending_session.started_at, joined_offset_ms=600_000)

    ConferenceRecording.objects.create(
        session=pending_session, kind=RecordingKind.PEER_AUDIO, participant=early,
        storage_path="audio-p1.mkv", started_offset_ms=0)
    ConferenceRecording.objects.create(
        session=pending_session, kind=RecordingKind.PEER_AUDIO, participant=late,
        storage_path="audio-p2.mkv", started_offset_ms=600_000)

    # Оба сказали «на пятой секунде своей дорожки» — но встречу это делит
    # на «в начале» и «через десять минут».
    def fake_transcribe(path, *, offset_ms=0):
        return [{"start_ms": 5_000 + offset_ms, "end_ms": 8_000 + offset_ms,
                 "text": f"реплика {path.name}", "confidence": 0.9}]

    monkeypatch.setattr(
        "apps.conference.services.transcript_service.transcribe_track",
        fake_transcribe)
    monkeypatch.setattr(tasks.compose_service, "raw_path",
                        lambda s, r: _FakePath(r.storage_path))
    monkeypatch.setattr(tasks, "_drop_raw_dir", lambda s: None)

    assert tasks.transcribe_session(pending_session.pk) == 2

    rows = list(pending_session.segments.order_by("start_ms"))
    assert [row.speaker_name for row in rows] == ["Иванов", "Петров"]
    assert [row.start_ms for row in rows] == [5_000, 605_000]

    pending_session.refresh_from_db()
    assert pending_session.transcript_state == TranscriptState.READY


def test_transcript_rerun_does_not_duplicate_segments(pending_session, monkeypatch):
    participant = ConferenceParticipant.objects.create(
        session=pending_session, display_name="Иванов", peer_id="p1",
        joined_at=pending_session.started_at)
    ConferenceRecording.objects.create(
        session=pending_session, kind=RecordingKind.PEER_AUDIO, participant=participant,
        storage_path="audio-p1.mkv")

    monkeypatch.setattr(
        "apps.conference.services.transcript_service.transcribe_track",
        lambda path, *, offset_ms=0: [
            {"start_ms": 0, "end_ms": 1000, "text": "раз", "confidence": None}])
    monkeypatch.setattr(tasks.compose_service, "raw_path",
                        lambda s, r: _FakePath(r.storage_path))
    monkeypatch.setattr(tasks, "_drop_raw_dir", lambda s: None)

    tasks.transcribe_session(pending_session.pk)
    pending_session.transcript_state = TranscriptState.PENDING
    pending_session.save(update_fields=["transcript_state"])
    tasks.transcribe_session(pending_session.pk)

    assert ConferenceTranscriptSegment.objects.filter(session=pending_session).count() == 1


def test_session_without_audio_is_marked_skipped(pending_session, monkeypatch):
    monkeypatch.setattr(tasks, "_drop_raw_dir", lambda s: None)
    assert tasks.transcribe_session(pending_session.pk) == 0
    pending_session.refresh_from_db()
    assert pending_session.transcript_state == TranscriptState.SKIPPED


class _FakePath:
    """Минимальный заменитель Path: сборщик проверяет exists() и имя."""

    def __init__(self, name: str) -> None:
        self.name = name

    def exists(self) -> bool:
        return True


# ── осиротевшие встречи ────────────────────────────────────────────────────

def test_orphan_session_is_closed_by_last_sign_of_life(db, organiser, monkeypatch,
                                                       settings):
    """SFU перезапустился посреди звонка. Незакрытая встреча держит частичный
    уникальный индекс комнаты — следующая встреча прилипла бы к ней."""
    settings.CONFERENCE_ORPHAN_HOURS = 6
    monkeypatch.setattr(
        "apps.conference.services.session_service.enqueue_processing",
        lambda session: None)

    started = timezone.now() - timedelta(hours=10)
    stale = ConferenceSession.objects.create(
        room_id="abandoned", started_at=started, expires_at=started + timedelta(days=25),
        recording_state=RecordingState.RECORDING)
    last_join = started + timedelta(minutes=20)
    ConferenceParticipant.objects.create(
        session=stale, display_name="Иванов", peer_id="p1", joined_at=last_join)

    assert tasks.reap_orphan_sessions() == 1

    stale.refresh_from_db()
    assert stale.ended_at == last_join
    # Длительность — по последнему признаку жизни, а не «до сейчас»: иначе
    # брошенная встреча получила бы десять часов.
    assert stale.duration_sec == 20 * 60
