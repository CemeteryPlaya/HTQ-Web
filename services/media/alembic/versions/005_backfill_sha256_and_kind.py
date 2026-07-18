"""Backfill sha256/kind/width/height for legacy files and enqueue thumbnails.

Revision ID: 0005_backfill_sha256
Revises: 0004_meta_and_variants
Create Date: 2026-05-05 01:00:00.000000

For each existing ``file_metadata`` row without sha256:

1. Read the file from local storage (S3 backfill is left for a separate
   admin job — synchronous boto3 calls inside Alembic are slow and noisy).
2. Compute sha256, set ``kind`` from mime, and read image dimensions where
   possible.
3. After the schema-only data fix-up is committed, no thumbnails are written
   here — that is delegated to ``make_variants`` workers, queued by an admin
   command (see ``services/media/scripts/enqueue_backfill.py``) so the
   migration cannot block the deploy on Pillow processing.

Both steps are best-effort: rows that can't be read (missing file, S3
backend, unreadable image) are left as-is and logged.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0005_backfill_sha256"
down_revision: Union[str, None] = "0004_meta_and_variants"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_logger = logging.getLogger("alembic.media.0005_backfill")


def _kind_from_mime(mime: str | None) -> str:
    if not mime:
        return "other"
    if mime.startswith("image/"):
        return "image"
    if mime.startswith("video/"):
        return "video"
    if mime.startswith("audio/"):
        return "audio"
    if mime.startswith("application/pdf") or mime.startswith("application/msword") or mime.startswith(
        "application/vnd.openxmlformats-officedocument"
    ):
        return "document"
    return "other"


def _image_dimensions(data: bytes) -> tuple[int, int] | None:
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        from io import BytesIO

        with Image.open(BytesIO(data)) as img:
            img.load()
            return img.width, img.height
    except Exception:
        return None


def upgrade() -> None:
    bind = op.get_bind()

    # The container always mounts the media volume at /app/data/media (see
    # docker-compose). For environments that override this, the operator can
    # set the env var ``MEDIA_ROOT`` for the migration command.
    import os

    media_root = Path(os.environ.get("MEDIA_ROOT", "/app/data/media"))
    if not media_root.exists():
        _logger.warning("media_root %s missing — skipping local backfill", media_root)
        return

    rows = bind.execute(
        sa.text(
            """
            SELECT id::text, path, mime, storage_backend
              FROM media.file_metadata
             WHERE sha256 IS NULL
               AND deleted_at IS NULL
            """
        )
    ).fetchall()

    update_stmt = sa.text(
        """
        UPDATE media.file_metadata
           SET sha256 = :sha,
               kind = :kind,
               width = :w,
               height = :h
         WHERE id = CAST(:id AS uuid)
        """
    )

    for file_id, path, mime, backend in rows:
        if backend != "local":
            continue  # S3 backfill handled out-of-band

        full = media_root / path
        if not full.exists() or not full.is_file():
            _logger.warning("backfill: missing file on disk id=%s path=%s", file_id, path)
            continue

        try:
            data = full.read_bytes()
        except OSError as exc:
            _logger.warning("backfill: read failed id=%s: %s", file_id, exc)
            continue

        sha = hashlib.sha256(data).hexdigest()
        kind = _kind_from_mime(mime)
        dims = _image_dimensions(data) if kind == "image" else None

        bind.execute(
            update_stmt,
            {
                "sha": sha,
                "kind": kind,
                "w": dims[0] if dims else None,
                "h": dims[1] if dims else None,
                "id": file_id,
            },
        )

    # Tag known avatars with scope='avatar' so the worker generates the
    # correct thumbnail set when ``enqueue_backfill`` fires. The user-service
    # ``users`` table lives in the ``public`` schema in current deploys; we
    # also probe ``auth.users`` for legacy/forked layouts. Skipped silently
    # if neither exists.
    users_table = bind.execute(
        sa.text(
            "SELECT COALESCE(to_regclass('public.users'), to_regclass('auth.users'))::text"
        )
    ).scalar()
    if users_table:
        bind.execute(
            sa.text(
                f"""
                UPDATE media.file_metadata AS fm
                   SET scope = 'avatar'
                 WHERE fm.scope <> 'avatar'
                   AND fm.id::text IN (
                       SELECT regexp_replace(u.avatar_url, '^.*/files/([0-9a-f-]{{36}}).*$', '\\1')
                         FROM {users_table} AS u
                        WHERE u.avatar_url IS NOT NULL
                          AND u.avatar_url ~ '/files/[0-9a-f-]{{36}}'
                   )
                """
            )
        )


def downgrade() -> None:
    # No-op: the data we filled in is informational and idempotent; reverting
    # would only re-introduce the gaps without a benefit.
    pass
