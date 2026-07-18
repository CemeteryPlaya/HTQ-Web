"""Weekly room-history archiver.

Layout::

    chats/<room_storage_key>/history/<YYYY>/<MM>/<DD>.jsonl

One JSONL line per message; one file per day covered by the archive window.
The scheduler runs this every Saturday 04:30 GMT+5 (configurable) and writes
the previous 7 days. Re-running is idempotent: each daily file is overwritten
on each run, so a missed Saturday is recovered on the next run.

Why JSONL: append-friendly format, parseable line-by-line, plays nicely with
``mc cat`` / ``aws s3 cp`` and any downstream ETL.
"""

from __future__ import annotations

import io
import json
from datetime import datetime, timedelta, timezone
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.logging import get_logger
from app.db import async_session_factory
from app.models.domain import ChatAttachment, Message, Room
from app.services.s3_storage import Storage, get_storage

log = get_logger(__name__)


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
        "updated_at": dt(getattr(message, "updated_at", None)),
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


async def _archive_room_day(
    session: AsyncSession,
    storage: Storage,
    room: Room,
    day_start: datetime,
) -> int:
    """Write one day of one room's messages. Returns message count."""
    day_end = day_start + timedelta(days=1)
    stmt = (
        select(Message)
        .where(
            Message.room_id == room.id,
            Message.created_at >= day_start,
            Message.created_at < day_end,
        )
        .order_by(Message.created_at.asc())
        .options(selectinload(Message.attachments))
    )
    rows = (await session.execute(stmt)).scalars().all()
    if not rows:
        return 0

    buffer = io.StringIO()
    for message in rows:
        line = json.dumps(
            _serialize_message(message, message.attachments),
            ensure_ascii=False,
        )
        buffer.write(line)
        buffer.write("\n")

    key = _history_object_key(room.storage_key, day_start)
    await storage.save(key, buffer.getvalue().encode("utf-8"), content_type="application/x-ndjson")
    return len(rows)


async def archive_recent_history(days: int = 7) -> dict:
    """Archive the last ``days`` calendar days for every room.

    Returns a small summary dict for logging. Intended to be called from the
    APScheduler weekly job and from an admin-only HTTP endpoint for manual
    re-runs / backfill.
    """
    storage = get_storage()
    now = datetime.now(timezone.utc)
    today = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    window_start = today - timedelta(days=days)

    summary = {"rooms": 0, "files_written": 0, "messages": 0, "window_start": window_start.isoformat()}

    async with async_session_factory() as session:
        rooms = (await session.execute(select(Room))).scalars().all()
        summary["rooms"] = len(rooms)
        for room in rooms:
            if room.storage_key is None:
                # Rooms without a storage_key never received an attachment;
                # still archive their history so admins can reconstruct it.
                continue
            for offset in range(days):
                day_start = window_start + timedelta(days=offset)
                count = await _archive_room_day(session, storage, room, day_start)
                if count:
                    summary["files_written"] += 1
                    summary["messages"] += count

    log.info("history_archive_run", **summary)
    return summary
