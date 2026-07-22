"""Pydantic-схемы тел запросов домена messenger — порт
``services/messenger/app/schemas/messenger.py`` (только тела запросов; формы
ответов собираются сериализаторами в ``apps/messenger/services/
messenger_service.py``, тот же принцип, что ``apps/hr/schemas.py``/
``apps/mail/schemas.py``).
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


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

    ``attachment_ids`` исходника — НЕ портируется (attachments — отдельная
    под-задача, ``ChatAttachment`` здесь ещё не существует, см.
    ``apps/messenger/models.py`` докстринг). Поле не объявлено здесь: если
    клиент всё же пришлёт его в теле, pydantic v2 молча проигнорирует лишний
    ключ (дефолтный ``model_config`` — ``extra="ignore"``), запрос не упадёт.
    """

    room_id: int
    content: str
    is_encrypted: bool = False
    metadata_json: Optional[dict] = None
