"""Pydantic-схемы аппки conference — тела запросов и формы ответов.

Две группы, и их не стоит смешивать: ``Internal*`` описывают то, что
присылает SFU (машина машине, поля техничные), остальные — то, что видит
браузер.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

# ── Внутренний канал: SFU → Django ─────────────────────────────────────────


class InternalSessionStart(BaseModel):
    room_id: str = Field(min_length=1, max_length=64)
    started_at: datetime | None = None
    created_by_id: int | None = None
    created_by_name: str = Field(default="", max_length=255)
    title: str = Field(default="", max_length=255)


class InternalSessionStarted(BaseModel):
    session_id: int
    started_at: datetime
    #: SFU спрашивает не «включить ли запись», а «пишем ли мы эту встречу» —
    #: решение принимает платформа (CONFERENCE_RECORDING_ENABLED), чтобы его
    #: можно было поменять в одном месте, не трогая конфиг SFU.
    recording_enabled: bool
    raw_dir: str


class InternalParticipant(BaseModel):
    peer_id: str = Field(min_length=1, max_length=64)
    display_name: str = Field(default="", max_length=255)
    user_id: int | None = None
    is_guest: bool = False
    action: str = Field(default="join", pattern="^(join|leave)$")
    at: datetime | None = None


class InternalEvent(BaseModel):
    kind: str = Field(min_length=1, max_length=24)
    peer_id: str | None = Field(default=None, max_length=64)
    at_ms: int | None = Field(default=None, ge=0)
    payload: dict | None = None


class InternalArtifact(BaseModel):
    """Одна сырая дорожка, которую рекордер дописал на том."""

    kind: str = Field(pattern="^(peer_audio|peer_video)$")
    peer_id: str = Field(min_length=1, max_length=64)
    #: Путь ОТНОСИТЕЛЬНО CONFERENCE_RAW_DIR. Абсолютный принимать нельзя:
    #: это путь из чужого контейнера, и подставлять его в файловые операции
    #: как есть — приглашение прочитать что-нибудь за пределами тома.
    rel_path: str = Field(min_length=1, max_length=512)
    started_offset_ms: int = Field(default=0, ge=0)
    size: int = Field(default=0, ge=0)


class InternalArtifacts(BaseModel):
    artifacts: list[InternalArtifact] = Field(default_factory=list, max_length=200)


class InternalSessionFinish(BaseModel):
    ended_at: datetime | None = None
    artifacts: list[InternalArtifact] = Field(default_factory=list, max_length=200)


class InternalAck(BaseModel):
    ok: bool = True
    session_id: int | None = None


# ── Публичные ответы ───────────────────────────────────────────────────────


class ParticipantRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int | None
    display_name: str
    is_guest: bool
    joined_at: datetime
    left_at: datetime | None
    joined_offset_ms: int
    #: Момент выхода в миллисекундах от начала встречи. ``None`` — участник
    #: досидел до конца. Считается ЗДЕСЬ, а не на фронте: два независимых
    #: вычисления одной величины со временем разъезжаются.
    left_offset_ms: int | None = None


class SessionListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    room_id: str
    title: str
    created_by_id: int | None
    created_by_name: str
    started_at: datetime
    ended_at: datetime | None
    duration_sec: int | None
    peak_participants: int
    recording_state: str
    transcript_state: str
    expires_at: datetime
    participant_count: int = 0
    has_recording: bool = False


class SessionListResponse(BaseModel):
    """Конверт списка.

    ⚠️ Полей здесь СЕМЬ, а не пять, и это существенно: axios-обёртка фронта
    (frontend/src/api/client.ts::unwrapPaginatedEnvelope) разворачивает
    конверт в голый массив ровно тогда, когда ключей ровно
    {items,total,page,pages,limit}. Лишние ключи — то, что оставляет конверт
    в целости, как у истории уведомлений с её unread_total.
    """

    items: list[SessionListItem]
    total: int
    page: int
    pages: int
    limit: int
    recorded_total: int
    active_total: int


class TodayItem(BaseModel):
    """Строка вкладки «Сегодня» — событие календаря плюс его судьба."""

    event_id: int
    room_id: str
    title: str
    start_at: datetime
    end_at: datetime
    #: scheduled — ещё не начиналась, live — идёт, finished — закончилась.
    status: str
    session_id: int | None = None
    is_organizer: bool = False
    participant_count: int = 0


class OverviewResponse(BaseModel):
    #: Часы сервера. Фронт решает «идёт ли сейчас» по ним, а не по часам
    #: машины пользователя: сбитые локальные часы иначе рисовали бы встречу
    #: как ещё не начавшуюся.
    server_time: datetime
    today: list[TodayItem] = Field(default_factory=list)
    active: list[SessionListItem] = Field(default_factory=list)


class TranscriptSegmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    participant_id: int | None
    speaker_name: str
    start_ms: int
    end_ms: int
    text: str
    confidence: float | None


class EventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    at_ms: int
    participant_id: int | None
    payload: dict | None


class SessionDetail(SessionListItem):
    error: str = ""
    purged_at: datetime | None = None
    participants: list[ParticipantRead] = Field(default_factory=list)
    #: Готово ли видео к показу. Отдельным полем, а не выводом из
    #: recording_state на фронте: состояний шесть, и правило «когда включать
    #: плеер» должно жить в одном месте — здесь.
    playable: bool = False
    #: Подписанные ссылки (``?sig=&exp=``), пригодные для ``<video src>`` и
    #: ``poster``: тег не отправляет Authorization, поэтому права проверяются
    #: здесь, при выдаче карточки, а не при каждом обращении плеера.
    #: См. services/signing.py.
    recording_url: str | None = None
    download_url: str | None = None
    poster_url: str | None = None


class TranscriptResponse(BaseModel):
    session_id: int
    state: str
    segments: list[TranscriptSegmentRead]
