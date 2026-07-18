"""Chat attachments — upload to S3 and serve via signed redirect.

URL flow:

1. Browser POSTs ``/upload/`` (multipart) — file streams into S3 under
   ``chats/<room>/<data_type>/<id>_<filename>``; a JSON metadata snapshot is
   written next to it.
2. The API response includes ``url = /file/{id}?sig=...&exp=...`` — an HMAC
   over ``id|exp``. Browsers can use this URL inside ``<img src>`` etc.
3. ``GET /file/{id}`` validates the signature, checks the caller is a room
   participant if a JWT is present, then 302-redirects to a fresh S3
   presigned URL (TTL = ``s3_presigned_url_ttl``).
"""

from __future__ import annotations

import uuid
from typing import Annotated, Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import TokenPayload, get_current_user, get_optional_user
from app.db import get_db_session
from app.models.domain import ChatAttachment, Room, RoomParticipant
from app.schemas.messenger import ChatAttachmentRead
from app.services.attachment_storage import (
    attachment_object_key,
    classify_attachment,
    get_storage,
    read_upload_to_buffer,
    sanitize_filename,
    write_attachment_metadata,
)
from app.services.audio_transmux import (
    should_transmux_to_ogg,
    transmux_webm_to_ogg,
)
from app.services.audit import record_action
from app.services.image_thumb import (
    THUMB_FORMAT,
    make_thumbnail,
    thumbnail_object_key,
)
from app.services.signed_url import signed_query, verify

router = APIRouter(tags=["attachments"])


def _public_url(attachment_id: uuid.UUID) -> str:
    return f"/api/messenger/v1/attachments/file/{attachment_id}?{signed_query(str(attachment_id))}"


@router.post("/upload/", response_model=ChatAttachmentRead, status_code=status.HTTP_201_CREATED)
async def upload_attachment(
    request: Request,
    room_id: Annotated[int, Form(...)],
    file: Annotated[UploadFile, File(...)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[TokenPayload, Depends(get_current_user)],
) -> ChatAttachment:
    participant = await session.get(RoomParticipant, (room_id, user.user_id))
    if not participant:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a participant")

    room = await session.get(Room, room_id)
    if not room:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Room not found")

    if room.storage_key is None:
        room.storage_key = uuid.uuid4()
        await session.flush()

    file_id = uuid.uuid4()
    filename = sanitize_filename(file.filename)
    content_type = file.content_type or "application/octet-stream"

    # Buffer the upload so we can transmux voice messages before S3 PUT.
    # WebM/Opus from Chromium MediaRecorder is repackaged into a real Ogg
    # container (stream copy — no re-encode), so the file the user later
    # downloads has matching extension/codec/container.
    buffer = await read_upload_to_buffer(file)
    if should_transmux_to_ogg(content_type, filename):
        repacked = await transmux_webm_to_ogg(buffer)
        if repacked is not None:
            buffer = repacked
            content_type = "audio/ogg"

    data_type = classify_attachment(content_type, filename)
    object_key = attachment_object_key(
        room_storage_key=room.storage_key,
        attachment_id=file_id,
        data_type=data_type,
        filename=filename,
    )

    storage = get_storage()
    await storage.save(object_key, buffer, content_type=content_type)
    size = len(buffer)

    # Generate a ≤ 256×256 thumbnail for images. Non-image attachments
    # silently skip this; SVG / corrupted files come back as (None, None, None).
    thumbnail_path: str | None = None
    width: int | None = None
    height: int | None = None
    if data_type == "images":
        thumb_bytes, width, height = make_thumbnail(buffer)
        if thumb_bytes is not None:
            thumbnail_path = thumbnail_object_key(original_key=object_key)
            await storage.save(
                thumbnail_path,
                thumb_bytes,
                content_type=f"image/{THUMB_FORMAT.lower()}",
            )

    attachment = ChatAttachment(
        id=file_id,
        room_id=room.id,
        filename=filename,
        content_type=content_type,
        data_type=data_type,
        storage_path=object_key,
        public_url=_public_url(file_id),
        thumbnail_path=thumbnail_path,
        width=width,
        height=height,
        size=size,
        uploaded_by=user.user_id,
    )
    session.add(attachment)
    await session.flush()
    await session.refresh(attachment)

    await write_attachment_metadata(
        storage=storage,
        room_storage_key=room.storage_key,
        attachment=attachment,
    )
    await record_action(
        session,
        user_id=user.user_id,
        action="upload_attachment",
        resource_type="ChatAttachment",
        resource_id=str(file_id),
        request=request,
        changes={
            "room_id": room.id,
            "filename": filename,
            "data_type": data_type,
            "storage_path": object_key,
        },
    )
    await session.commit()
    await session.refresh(attachment)
    return attachment


@router.get("/file/{attachment_id}", include_in_schema=False)
async def serve_attachment(
    attachment_id: uuid.UUID,
    sig: Annotated[str, Query(...)],
    exp: Annotated[int, Query(...)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[Optional[TokenPayload], Depends(get_optional_user)],
) -> RedirectResponse:
    """Validate the signed URL, check participation when a JWT is present,
    then 302 to a fresh S3 presigned URL.

    The signed URL is the public contract — it works inside ``<img src>``
    where the browser cannot send an Authorization header. When the request
    DOES carry a JWT (XHR/fetch flows), we additionally enforce that the
    caller is a participant of the attachment's room.
    """
    if not verify(str(attachment_id), sig, exp):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid or expired signature")

    attachment = await session.get(ChatAttachment, attachment_id)
    if not attachment or not attachment.storage_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found")

    if user is not None and attachment.room_id is not None:
        participant = await session.get(RoomParticipant, (attachment.room_id, user.user_id))
        if not participant:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a participant")

    storage = get_storage()
    presigned = await storage.presigned_get_url(attachment.storage_path)
    return RedirectResponse(url=presigned, status_code=status.HTTP_302_FOUND)


@router.get("/file/{attachment_id}/thumb", include_in_schema=False)
async def serve_attachment_thumb(
    attachment_id: uuid.UUID,
    sig: Annotated[str, Query(...)],
    exp: Annotated[int, Query(...)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[Optional[TokenPayload], Depends(get_optional_user)],
) -> RedirectResponse:
    """Same flow as ``/file/{id}`` but redirects to the thumbnail.

    Falls back to the original when ``thumbnail_path`` is NULL (image
    couldn't be processed, or a row uploaded before migration 006). The
    caller stays inside the same signed-URL contract — UI can swap
    ``/file/{id}`` ↔ ``/file/{id}/thumb`` without re-signing.
    """
    if not verify(str(attachment_id), sig, exp):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid or expired signature")

    attachment = await session.get(ChatAttachment, attachment_id)
    if not attachment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found")

    if user is not None and attachment.room_id is not None:
        participant = await session.get(RoomParticipant, (attachment.room_id, user.user_id))
        if not participant:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a participant")

    target_path = attachment.thumbnail_path or attachment.storage_path
    if not target_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found")

    storage = get_storage()
    presigned = await storage.presigned_get_url(target_path)
    return RedirectResponse(url=presigned, status_code=status.HTTP_302_FOUND)
