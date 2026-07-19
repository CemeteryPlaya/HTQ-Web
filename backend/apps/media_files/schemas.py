"""Pydantic schemas for file metadata — wire shape for the upload response.

Ported from ``services/media/app/schemas/file.py``. Field names and the
``serialize_file`` shape (flattened ``variants: {name: url}`` map, computed
``url``) are kept identical to the source so the frontend (which already
expects this shape — see ``frontend/src/api/media.ts``, ``AdminNews.tsx``,
``NewsEditor.tsx``) doesn't need to change.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class FileVariantRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    variant: str
    mime: str
    width: int
    height: int
    size: int


class FileMetadataRead(BaseModel):
    """Wire shape for a file response.

    Built explicitly in the view (not via ``from_attributes``) so we can
    splat in the variant URL map and the canonical download URL without
    fighting Pydantic over computed fields plus relationships — same
    reasoning as the source.
    """

    id: uuid.UUID
    path: str
    original_filename: str
    owner_id: Optional[int]
    size: int
    mime: str
    is_public: bool
    sha256: Optional[str] = None
    kind: str = "other"
    scope: str = "generic"
    width: Optional[int] = None
    height: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    url: str
    variants: dict[str, str] = {}


def serialize_file(meta) -> FileMetadataRead:
    """Build a ``FileMetadataRead`` from a ``FileMetadata`` model instance.

    Reads the ``variants`` reverse relation and flattens it into
    ``{variant_name: url}``. Freshly-uploaded files have no variants yet
    (the Celery task that produces them runs after this is called, or —
    with ``CELERY_TASK_ALWAYS_EAGER`` in tests — has already run and
    written rows by the time the caller re-fetches ``meta.variants``); an
    empty map means the frontend falls back to the original.
    """
    file_id = str(meta.id)
    variants_map: dict[str, str] = {
        v.variant: f"/api/media/v1/files/{file_id}/{v.variant}"
        for v in meta.variants.all()
    }

    return FileMetadataRead(
        id=meta.id,
        path=meta.path,
        original_filename=meta.original_filename,
        owner_id=meta.owner_id,
        size=meta.size,
        mime=meta.mime,
        is_public=meta.is_public,
        sha256=meta.sha256,
        kind=meta.kind,
        scope=meta.scope,
        width=meta.width,
        height=meta.height,
        created_at=meta.created_at,
        updated_at=meta.updated_at,
        url=f"/api/media/v1/files/{file_id}",
        variants=variants_map,
    )
