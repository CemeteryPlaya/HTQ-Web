"""Pydantic schemas for file metadata."""

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

    Built explicitly in the route handler (not via ``from_attributes``) so we
    can splat in the variant URL map and the canonical download URL without
    fighting Pydantic over computed fields plus relationships.
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


class FileMetadataUpdate(BaseModel):
    is_public: Optional[bool] = None
    original_filename: Optional[str] = None


class SignedUrlResponse(BaseModel):
    url: str
    exp: int


def serialize_file(meta) -> FileMetadataRead:
    """Build a ``FileMetadataRead`` from a ``FileMetadata`` ORM row.

    Reads the ``variants`` relationship (populated via lazy='selectin') and
    flattens it into ``{variant_name: url}``. If the worker hasn't produced
    variants yet the map is simply empty — the frontend can fall back to
    the original.
    """
    file_id = str(meta.id)
    variants_map: dict[str, str] = {}
    for v in getattr(meta, "variants", []) or []:
        variants_map[v.variant] = f"/api/media/v1/files/{file_id}/{v.variant}"

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
