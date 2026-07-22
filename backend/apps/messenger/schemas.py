"""Pydantic-схемы тел запросов домена messenger — порт
``services/messenger/app/schemas/messenger.py`` (только тела запросов; формы
ответов собираются сериализаторами в ``apps/messenger/services/
messenger_service.py``, тот же принцип, что ``apps/hr/schemas.py``/
``apps/mail/schemas.py``).
"""
from __future__ import annotations

import uuid
from typing import Optional

from pydantic import BaseModel, Field


class RoomCreateRequest(BaseModel):
    """Порт ``schemas/messenger.py::RoomCreate``. ``room_type`` — обычная
    ``str`` без ``Literal``/enum-ограничения, буквально как в исходнике
    (колонка тоже без CheckConstraint, см. ``apps/messenger/models.py::
    RoomType``)."""

    name: Optional[str] = None
    room_type: str = "direct"
    is_e2ee: bool = False
    avatar_url: Optional[str] = None
    # ids всех участников, БЕЗ вызывающего (сервис добавляет его сам как
    # admin) — для direct-чата список должен содержать ровно один id.
    participant_ids: list[int]


class RoomUpdateRequest(BaseModel):
    """Порт ``schemas/messenger.py::RoomUpdate``. Оба поля опциональны —
    ``None`` значит «не трогать», пустая строка — явный способ очистить
    значение (сервис делает ``.strip() or None``, как исходник)."""

    name: Optional[str] = None
    avatar_url: Optional[str] = None


class MessageCreateRequest(BaseModel):
    """Порт ``schemas/messenger.py::MessageCreate``.

    ``attachment_ids`` (attachments-под-задача, PLAN.md §6.5): ссылки на
    ранее загруженные (``POST /attachments/upload/``), ещё не прикреплённые
    вложения этой же комнаты — сервис привязывает их к создаваемому
    сообщению (``apps.messenger.services.attachment_service.
    attach_to_message``), см. ``messenger_service.py::send_message``.
    """

    room_id: int
    content: str
    is_encrypted: bool = False
    metadata_json: Optional[dict] = None
    attachment_ids: list[uuid.UUID] = []


class UserKeyUploadRequest(BaseModel):
    """Порт ``schemas/messenger.py::UserKeyCreate`` (attachments-под-задача,
    PLAN.md §6.5)."""

    device_id: str
    public_identity_key: str
    signed_pre_key: str
    signature: str


class UserReplicaIngestRequest(BaseModel):
    """Порт ``schemas/messenger.py::UserReplicaRead`` — используется ИСКЛЮЧИТЕЛЬНО
    как тело ``POST /users/ingest`` (workers/admin под-задача, PLAN.md §6.5).

    Р2 (см. ``apps/messenger/views.py::ingest_user_replica`` докстринг):
    ``chat_user_replicas`` не портируется — этот эндпойнт ничего не
    сохраняет, только валидирует форму тела ради обратной совместимости с
    любым ещё не мигрированным вызывающим. Поля — буквальный список исходной
    ``UserReplicaRead`` (``id``/``username``/``first_name``/``last_name``/
    ``avatar_url``/``is_active``/``is_bot``)."""

    id: int
    username: str
    first_name: str
    last_name: str
    avatar_url: Optional[str] = None
    is_active: bool
    is_bot: bool = False


class InternalBotMessageRequest(BaseModel):
    """Порт ``app/api/v1/internal.py::BotMessageRequest`` (workers/admin
    под-задача, PLAN.md §6.5) — тело ``POST /internal/bot-message``."""

    bot: str
    user_id: int
    text: str = Field(..., min_length=1, max_length=4000)
    metadata: Optional[dict] = None
