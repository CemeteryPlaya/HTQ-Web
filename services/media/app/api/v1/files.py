"""Files API endpoints.

Routing layer is intentionally thin: parsing/auth + delegation to
``app.services.media_service`` for the upload pipeline. Variant + signed-URL
endpoints live here too because they're query-only and don't earn their own
service module.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import (
    TokenPayload,
    get_current_user,
    get_optional_user,
    require_admin,
)
from app.core.logging import get_logger
from app.db import get_db_session
from app.models.file_metadata import FileMetadata
from app.models.file_variant import FileVariant
from app.schemas.file import (
    FileMetadataRead,
    FileMetadataUpdate,
    SignedUrlResponse,
    serialize_file,
)
from app.services.audit import record_action
from app.services.media_service import UploadValidationError, upload_file_bytes
from app.services.signed_url import sign as sign_url
from app.services.signed_url import verify as verify_signature
from app.storage import get_storage


router = APIRouter(tags=["files"])
log = get_logger(__name__)


def _quote_filename(name: str) -> str:
    """Strip CRLF and double-quotes from a filename used in a quoted-string
    Content-Disposition header (RFC 6266) to block header-injection."""
    return name.replace('"', "").replace("\r", "").replace("\n", "")


def _resolve_owner_id(user: TokenPayload, request: Request) -> Optional[int]:
    """For S2S calls (service JWT) the originating user is in X-User-Id."""
    if user.user_id is not None:
        return user.user_id
    if user.is_service:
        raw = request.headers.get("x-user-id")
        if raw:
            try:
                return int(raw)
            except ValueError:
                return None
    return None


def _can_access_private(user: Optional[TokenPayload], meta: FileMetadata) -> bool:
    if user is None:
        return False
    if user.is_admin:
        return True
    if user.is_service:
        # S2S calls are trusted for read-through; the calling service is
        # expected to have already gated on the end-user.
        return True
    return user.user_id == meta.owner_id


# ─── Upload ─────────────────────────────────────────────────────────────────


@router.post("/", response_model=FileMetadataRead, status_code=status.HTTP_201_CREATED)
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
    is_public: Optional[bool] = Form(None),
    scope: str = Form("generic"),
    session: AsyncSession = Depends(get_db_session),
    user: TokenPayload = Depends(get_current_user),
) -> FileMetadataRead:
    """Upload a new file.

    The pipeline (magic-mime detection, size/scope validation, EXIF strip
    via Pillow, sha256, storage write, FileMetadata persistence) lives in
    ``app.services.media_service``. This route handles HTTP concerns only.
    """
    data = await file.read()
    owner_id = _resolve_owner_id(user, request)

    try:
        result = await upload_file_bytes(
            session,
            data=data,
            declared_mime=file.content_type,
            original_filename=file.filename or "",
            scope=scope,
            requested_is_public=is_public,
            owner_id=owner_id,
        )
    except UploadValidationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    meta = result.meta

    if not result.deduplicated:
        await record_action(
            session,
            user_id=owner_id,
            action="file_uploaded",
            resource_type="FileMetadata",
            resource_id=str(meta.id),
            changes={
                "path": meta.path,
                "size": meta.size,
                "mime": meta.mime,
                "kind": meta.kind,
                "scope": meta.scope,
                "sha256": meta.sha256,
                "is_public": meta.is_public,
                "via_service": user.is_service,
            },
            request=request,
        )
        log.info(
            "file_uploaded",
            file_id=str(meta.id),
            size=meta.size,
            owner_id=owner_id,
            scope=meta.scope,
            kind=meta.kind,
            is_public=meta.is_public,
            via_service=user.is_service,
        )

    if result.enqueue_variants:
        from app.workers.actors import make_variants

        make_variants.send(str(meta.id))

    return serialize_file(meta)


# ─── Download (original) ────────────────────────────────────────────────────


@router.get("/{file_id}")
async def download_file(
    request: Request,
    file_id: uuid.UUID,
    sig: Optional[str] = Query(None),
    exp: Optional[int] = Query(None),
    session: AsyncSession = Depends(get_db_session),
    user: Optional[TokenPayload] = Depends(get_optional_user),
) -> Response:
    """Download the original file with Range support (206 Partial Content)."""
    meta = await session.get(FileMetadata, file_id)
    if not meta or meta.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")

    if not meta.is_public:
        if sig and exp and verify_signature(str(meta.id), "original", sig, int(exp)):
            pass  # signed URL grants access
        elif _can_access_private(user, meta):
            pass
        elif user is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        else:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)

    storage = get_storage()
    if not await storage.exists(meta.path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="File physically missing"
        )

    total = meta.size
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Type": meta.mime,
        "Content-Disposition": f'inline; filename="{_quote_filename(meta.original_filename)}"',
        "ETag": f'"{meta.id}-{meta.updated_at.timestamp()}"',
    }

    range_header = request.headers.get("Range")
    if range_header:
        try:
            r = range_header.replace("bytes=", "").split("-", 1)
            start = int(r[0]) if r[0] else 0
            end = int(r[1]) if len(r) > 1 and r[1] else total - 1
            if start >= total or end >= total or start > end:
                headers["Content-Range"] = f"bytes */{total}"
                return Response(
                    status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE,
                    headers=headers,
                )
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid Range Header"
            )
        headers["Content-Range"] = f"bytes {start}-{end}/{total}"
        headers["Content-Length"] = str(end - start + 1)
        data = await storage.open(meta.path, byte_range=(start, end))
        return Response(
            content=data, status_code=status.HTTP_206_PARTIAL_CONTENT, headers=headers
        )

    headers["Content-Length"] = str(total)
    data = await storage.open(meta.path)
    return Response(content=data, headers=headers)


# ─── Variant download ───────────────────────────────────────────────────────


@router.get("/{file_id}/{variant}")
async def download_variant(
    request: Request,
    file_id: uuid.UUID,
    variant: str,
    sig: Optional[str] = Query(None),
    exp: Optional[int] = Query(None),
    session: AsyncSession = Depends(get_db_session),
    user: Optional[TokenPayload] = Depends(get_optional_user),
) -> Response:
    """Serve a derived variant (thumb_32 / thumb_96 / preview_1024 / ...).

    Returns 404 if the variant has not been produced yet — the frontend
    should fall back to the original ``/{file_id}`` URL.
    """
    meta = await session.get(FileMetadata, file_id)
    if not meta or meta.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")

    if not meta.is_public:
        if sig and exp and verify_signature(str(meta.id), variant, sig, int(exp)):
            pass
        elif _can_access_private(user, meta):
            pass
        elif user is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        else:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)

    stmt = select(FileVariant).where(
        FileVariant.file_id == file_id, FileVariant.variant == variant
    )
    res = await session.execute(stmt)
    fv = res.scalar_one_or_none()
    if fv is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Variant '{variant}' not available",
        )

    storage = get_storage()
    if not await storage.exists(fv.path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Variant physically missing"
        )

    headers = {
        "Content-Type": fv.mime,
        "Content-Length": str(fv.size),
        "ETag": f'"{fv.id}"',
        "Cache-Control": "public, max-age=31536000, immutable" if meta.is_public else "private, max-age=300",
    }
    data = await storage.open(fv.path)
    return Response(content=data, headers=headers)


# ─── Signed URL ─────────────────────────────────────────────────────────────


@router.post("/{file_id}/sign", response_model=SignedUrlResponse)
async def issue_signed_url(
    file_id: uuid.UUID,
    variant: str = Query("original"),
    ttl: int = Query(3600, ge=60, le=24 * 3600),
    session: AsyncSession = Depends(get_db_session),
    user: TokenPayload = Depends(get_current_user),
) -> SignedUrlResponse:
    """Mint a short-lived HMAC-signed URL so the browser can fetch a private
    file via ``<img src>`` without an Authorization header.

    Only the owner / admin / a calling service may sign on behalf of a file.
    Public files don't need signing — return a plain URL anyway so callers
    can use this endpoint uniformly.
    """
    meta = await session.get(FileMetadata, file_id)
    if not meta or meta.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")

    if not _can_access_private(user, meta) and not meta.is_public:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)

    base = (
        f"/api/media/v1/files/{meta.id}"
        if variant == "original"
        else f"/api/media/v1/files/{meta.id}/{variant}"
    )

    if meta.is_public:
        # No need to sign; expose a far-future exp for cache-busting hint only.
        far_future = int(datetime.datetime.now(datetime.timezone.utc).timestamp()) + ttl
        return SignedUrlResponse(url=base, exp=far_future)

    sig, exp_ts = sign_url(str(meta.id), variant, ttl=ttl)
    return SignedUrlResponse(url=f"{base}?sig={sig}&exp={exp_ts}", exp=exp_ts)


# ─── List / Update / Delete ────────────────────────────────────────────────


@router.get("/", response_model=list[FileMetadataRead])
async def list_files(
    session: AsyncSession = Depends(get_db_session),
    user: TokenPayload = Depends(require_admin),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[FileMetadataRead]:
    """List all files (Admin only)."""
    stmt = (
        select(FileMetadata)
        .where(FileMetadata.deleted_at.is_(None))
        .order_by(FileMetadata.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await session.execute(stmt)
    rows = list(result.scalars().all())
    return [serialize_file(r) for r in rows]


@router.patch("/{file_id}", response_model=FileMetadataRead)
async def update_file_metadata(
    request: Request,
    file_id: uuid.UUID,
    payload: FileMetadataUpdate,
    session: AsyncSession = Depends(get_db_session),
    user: TokenPayload = Depends(get_current_user),
) -> FileMetadataRead:
    meta = await session.get(FileMetadata, file_id)
    if not meta or meta.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")

    if user.user_id != meta.owner_id and not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)

    changes = payload.model_dump(exclude_unset=True)
    for k, v in changes.items():
        setattr(meta, k, v)
    await session.flush()

    await record_action(
        session,
        user_id=user.user_id,
        action="file_metadata_updated",
        resource_type="FileMetadata",
        resource_id=str(meta.id),
        changes=changes,
        request=request,
    )
    return serialize_file(meta)


@router.delete("/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_file(
    request: Request,
    file_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    user: TokenPayload = Depends(get_current_user),
) -> None:
    """Soft-delete a file. The physical bytes (and variants) are reaped by
    ``purge_soft_deleted`` after ``settings.soft_delete_grace_days`` so the
    delete remains reversible for a grace period.
    """
    meta = await session.get(FileMetadata, file_id)
    if not meta or meta.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")

    if user.user_id != meta.owner_id and not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)

    meta.deleted_at = datetime.datetime.now(datetime.timezone.utc)
    await session.flush()

    await record_action(
        session,
        user_id=user.user_id,
        action="file_deleted",
        resource_type="FileMetadata",
        resource_id=str(file_id),
        changes={"path": meta.path, "soft_delete": True},
        request=request,
    )
    log.info("file_soft_deleted", file_id=str(file_id), by=user.user_id)
