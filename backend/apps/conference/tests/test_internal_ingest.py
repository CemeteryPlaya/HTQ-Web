"""Приём фактов о встрече от SFU.

Главное свойство этого канала — **идемпотентность**. Сеть между
контейнерами теряет ответы, SFU повторяет запрос, и повтор не должен
раздваивать встречу, плодить участников или запускать вторую сборку видео.
Второе по важности — что канал закрыт: он пишет в базу без всякого
пользователя, и открытым его оставлять нельзя.
"""

from __future__ import annotations

import json

import pytest
from django.test import Client
from django.utils import timezone

from apps.conference.models import (
    ConferenceParticipant,
    ConferenceRecording,
    ConferenceSession,
    RecordingKind,
    RecordingState,
)

from .conftest import BASE

pytestmark = pytest.mark.django_db


def post(client: Client, path: str, payload: dict, headers: dict):
    return client.post(f"{BASE}{path}", data=json.dumps(payload),
                       content_type="application/json", **headers)


# ── защита канала ──────────────────────────────────────────────────────────

def test_no_token_is_rejected(client, internal):
    """Без секрета — 403, а не запись в базу."""
    response = post(client, "/internal/sessions", {"room_id": "r1"}, {})
    assert response.status_code == 403
    assert ConferenceSession.objects.count() == 0


def test_wrong_token_is_rejected(client, internal):
    response = post(client, "/internal/sessions", {"room_id": "r1"},
                    {"HTTP_X_HTQ_INTERNAL_TOKEN": "не тот"})
    assert response.status_code == 403
    assert ConferenceSession.objects.count() == 0


def test_unset_secret_closes_the_channel(client, settings):
    """Пустой CONFERENCE_INTERNAL_TOKEN ЗАКРЫВАЕТ приём, а не открывает всем.

    Забытая переменная окружения не должна превращать внутренний канал в
    анонимную ручку записи в БД.
    """
    settings.CONFERENCE_INTERNAL_TOKEN = ""
    response = post(client, "/internal/sessions", {"room_id": "r1"},
                    {"HTTP_X_HTQ_INTERNAL_TOKEN": "что угодно"})
    assert response.status_code == 403


# ── идемпотентность ────────────────────────────────────────────────────────

def test_repeated_start_returns_the_same_session(client, internal):
    """SFU мог перезапуститься посреди звонка и повторить старт."""
    first = post(client, "/internal/sessions",
                 {"room_id": "r1", "created_by_id": 7,
                  "created_by_name": "Иванов"}, internal)
    second = post(client, "/internal/sessions",
                  {"room_id": "r1", "created_by_id": 9,
                   "created_by_name": "Петров"}, internal)

    assert first.status_code == second.status_code == 200
    assert first.json()["session_id"] == second.json()["session_id"]
    assert ConferenceSession.objects.count() == 1
    # Автор — тот, кто пришёл первым.
    assert ConferenceSession.objects.get().created_by_name == "Иванов"


def test_new_session_after_previous_one_ended(client, internal):
    """Комната переиспользуется: следующая встреча — НОВАЯ строка."""
    first_id = post(client, "/internal/sessions", {"room_id": "r1"},
                    internal).json()["session_id"]
    post(client, f"/internal/sessions/{first_id}/finish", {}, internal)

    second_id = post(client, "/internal/sessions", {"room_id": "r1"},
                     internal).json()["session_id"]
    assert second_id != first_id
    assert ConferenceSession.objects.count() == 2


def test_repeated_join_does_not_duplicate_participant(client, internal):
    session_id = post(client, "/internal/sessions", {"room_id": "r1"},
                      internal).json()["session_id"]
    payload = {"peer_id": "peer-1", "display_name": "Иванов",
               "user_id": 7, "is_guest": False, "action": "join"}

    post(client, f"/internal/sessions/{session_id}/participants", payload, internal)
    post(client, f"/internal/sessions/{session_id}/participants", payload, internal)

    assert ConferenceParticipant.objects.filter(session_id=session_id).count() == 1


def test_repeated_finish_does_not_enqueue_twice(client, internal, monkeypatch):
    """Повторный finish не запускает вторую сборку того же видео."""
    calls: list[int] = []
    monkeypatch.setattr(
        "apps.conference.services.session_service.enqueue_processing",
        lambda session: calls.append(session.pk),
    )

    session_id = post(client, "/internal/sessions", {"room_id": "r1"},
                      internal).json()["session_id"]
    post(client, f"/internal/sessions/{session_id}/finish", {}, internal)
    post(client, f"/internal/sessions/{session_id}/finish", {}, internal)

    assert calls == [session_id]


# ── журнал встречи ─────────────────────────────────────────────────────────

def test_leave_closes_participation_and_finish_closes_the_rest(client, internal):
    session_id = post(client, "/internal/sessions", {"room_id": "r1"},
                      internal).json()["session_id"]
    for peer in ("peer-1", "peer-2"):
        post(client, f"/internal/sessions/{session_id}/participants",
             {"peer_id": peer, "display_name": peer, "action": "join"}, internal)

    post(client, f"/internal/sessions/{session_id}/participants",
         {"peer_id": "peer-1", "display_name": "peer-1", "action": "leave"}, internal)
    post(client, f"/internal/sessions/{session_id}/finish", {}, internal)

    # Тот, кто не прислал leave (закрылась вкладка), всё равно должен быть
    # закрыт — иначе он навсегда останется «на встрече».
    assert not ConferenceParticipant.objects.filter(
        session_id=session_id, left_at__isnull=True).exists()

    session = ConferenceSession.objects.get(pk=session_id)
    assert session.ended_at is not None
    assert session.peak_participants == 2


def test_artifacts_are_registered_and_linked_to_participants(client, internal):
    session_id = post(client, "/internal/sessions", {"room_id": "r1"},
                      internal).json()["session_id"]
    post(client, f"/internal/sessions/{session_id}/participants",
         {"peer_id": "peer-1", "display_name": "Иванов", "action": "join"}, internal)

    response = post(client, f"/internal/sessions/{session_id}/artifacts", {
        "artifacts": [{
            "kind": "peer_audio", "peer_id": "peer-1",
            "rel_path": "audio-peer-1-abc.mkv",
            "started_offset_ms": 1500, "size": 4096,
        }],
    }, internal)
    assert response.status_code == 200

    recording = ConferenceRecording.objects.get(session_id=session_id)
    assert recording.kind == RecordingKind.PEER_AUDIO
    assert recording.started_offset_ms == 1500
    assert recording.participant.display_name == "Иванов"


@pytest.mark.parametrize("evil", [
    "../../etc/passwd",
    "/etc/passwd",
    "sub/../../escape.mkv",
])
def test_traversal_paths_are_refused(client, internal, evil):
    """Путь приезжает из ЧУЖОГО контейнера и потом идёт в файловые операции
    сборщика. Принимать `..` или ведущий слэш нельзя: это превратило бы
    сообщение о записи в чтение (а после уборки — и в удаление) произвольного
    файла воркера."""
    session_id = post(client, "/internal/sessions", {"room_id": "r1"},
                      internal).json()["session_id"]

    post(client, f"/internal/sessions/{session_id}/artifacts", {
        "artifacts": [{"kind": "peer_audio", "peer_id": "p", "rel_path": evil}],
    }, internal)

    assert ConferenceRecording.objects.count() == 0


def test_finish_marks_recording_for_processing(client, internal, monkeypatch, settings):
    settings.CONFERENCE_RECORDING_ENABLED = True
    monkeypatch.setattr(
        "apps.conference.services.session_service.enqueue_processing",
        lambda session: None,
    )
    session_id = post(client, "/internal/sessions", {"room_id": "r1"},
                      internal).json()["session_id"]
    assert ConferenceSession.objects.get(pk=session_id).recording_state == (
        RecordingState.RECORDING)

    post(client, f"/internal/sessions/{session_id}/finish", {}, internal)
    session = ConferenceSession.objects.get(pk=session_id)
    assert session.recording_state == RecordingState.PROCESSING
    assert session.duration_sec is not None
    assert session.ended_at <= timezone.now()
