"""Weekly room-history archiver — порт ``services/messenger/app/services/
history_archive.py`` (workers/admin под-задача, PLAN.md §6.5, последняя
под-задача messenger).

Layout — БЕЗ ИЗМЕНЕНИЙ от исходника::

    chats/<room_storage_key>/history/<YYYY>/<MM>/<DD>.jsonl

Один JSONL-объект на сообщение; один файл на день окна архивации. Повторный
запуск идемпотентен: каждый дневной файл перезаписывается на каждом
прогоне, так что пропущенная суббота восстанавливается на следующем прогоне.

Storage — ``htqweb.storage.get_storage()`` (ОБЩИЙ, синхронный S3/MinIO-клиент,
см. ``apps/messenger/services/attachment_service.py`` докстринг про запрет
собственного клона ``s3_storage.py``). Это архивный bulk-дамп истории комнат,
НЕ пользовательские вложения — поэтому здесь сознательно НЕ используется
``apps.media_files.interface.store_file()`` (тот создал бы по ``FileMetadata``
строке на каждый ежедневный JSONL-файл каждой комнаты — лишний и
семантически неверный учёт для внутреннего архивного дампа, у которого нет ни
signed-URL, ни variants, ни "владельца"-пользователя). Прямой
``htqweb.storage.get_storage()`` — тот же самый общий модуль, что уже
использует ``apps.cms``/``apps.media_files`` сами по себе — не новый клиент,
общий.

Вызывается из двух мест (тот же дуализм, что и в исходнике):
  * ``apps/messenger/tasks.py::archive_room_history`` — недельный beat-крон
    (~сб 04:30 GMT+5).
  * ``apps/messenger/views.py::admin_trigger_history_archive`` — ручной
    backfill/re-run (``POST /admin/history/archive?days=``).

Оба вызывают ЭТУ ЖЕ функцию — никакой дублирующей логики.

Тесты подменяют ``get_storage`` в этом модуле (``monkeypatch``) на
in-memory-дубль (``_FakeStorage``, тот же приём, что ``apps/hr/tests/
test_department_files_api.py``) — без живой сети/MinIO.
"""
from __future__ import annotations

import io
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Iterable

from htqweb.storage import Storage, get_storage

from apps.messenger.models import ChatAttachment, Message, Room

logger = logging.getLogger(__name__)


def _history_object_key(room_storage_key, day: datetime) -> str:
    return (
        f"chats/{room_storage_key}/history/"
        f"{day:%Y}/{day:%m}/{day:%d}.jsonl"
    )


def _serialize_message(message: Message, attachments: Iterable[ChatAttachment]) -> dict:
    def dt(value):
        return value.isoformat() if value is not None else None

    return {
        "id": str(message.id),
        "room_id": message.room_id,
        "sender_id": message.sender_id,
        "content": message.content,
        "is_encrypted": message.is_encrypted,
        "is_edited": message.is_edited,
        "metadata": message.metadata_json,
        "created_at": dt(message.created_at),
        "updated_at": dt(message.updated_at),
        "attachments": [
            {
                "id": str(a.id),
                "filename": a.filename,
                "size": a.size,
                "content_type": a.content_type,
                "data_type": a.data_type,
                "storage_path": a.storage_path,
            }
            for a in attachments
        ],
    }


def _archive_room_day(storage: Storage, room: Room, day_start: datetime) -> int:
    """Пишет один день одной комнаты. Возвращает число сообщений."""
    day_end = day_start + timedelta(days=1)
    messages = list(
        Message.objects.filter(
            room_id=room.id, created_at__gte=day_start, created_at__lt=day_end,
        ).order_by("created_at").prefetch_related("attachments")
    )
    if not messages:
        return 0

    buffer = io.StringIO()
    for message in messages:
        line = json.dumps(
            _serialize_message(message, message.attachments.all()),
            ensure_ascii=False,
        )
        buffer.write(line)
        buffer.write("\n")

    key = _history_object_key(room.storage_key, day_start)
    storage.save(key, buffer.getvalue().encode("utf-8"), content_type="application/x-ndjson")
    return len(messages)


def archive_recent_history(days: int = 7) -> dict:
    """Архивирует последние ``days`` календарных дней для каждой комнаты.

    Возвращает сводку для логирования — вызывается и из beat-задачи
    (``apps/messenger/tasks.py::archive_room_history``), и из admin-эндпойнта
    ручного backfill (``apps/messenger/views.py::admin_trigger_history_archive``).
    """
    storage = get_storage()
    now = datetime.now(timezone.utc)
    today = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    window_start = today - timedelta(days=days)

    summary = {"rooms": 0, "files_written": 0, "messages": 0, "window_start": window_start.isoformat()}

    # Исходник пропускал комнаты с ``storage_key is None`` («никогда не
    # получали вложение») — в этом порту ``Room.storage_key`` НЕ nullable
    # (``default=uuid.uuid4``, см. apps/messenger/models.py::Room), каждая
    # комната всегда несёт значение -> эта ветка структурно недостижима и
    # сознательно не переносится (не пропускаем ни одну комнату).
    rooms = list(Room.objects.all())
    summary["rooms"] = len(rooms)
    for room in rooms:
        for offset in range(days):
            day_start = window_start + timedelta(days=offset)
            count = _archive_room_day(storage, room, day_start)
            if count:
                summary["files_written"] += 1
                summary["messages"] += count

    logger.info("history_archive_run %s", summary)
    return summary
