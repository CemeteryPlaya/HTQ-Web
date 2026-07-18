"""Contact request endpoints — ``/api/cms/v1/contact-requests/*``.

- ``POST /`` is public with rate limiting (anonymous form).
- Everything else requires admin.
"""

from datetime import datetime, timezone
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import TokenPayload, require_admin
from app.core.logging import get_logger
from app.core.settings import settings
from app.db import get_db_session
from app.models.contact_request import ContactRequest
from app.schemas.contact_request import (
    ContactRequestCreate,
    ContactRequestRead,
    ContactRequestReply,
    ContactRequestStats,
    ContactRequestUpdate,
)
from app.services.audit import record_action


router = APIRouter(tags=["contact-requests"])
limiter = Limiter(key_func=get_remote_address)
log = get_logger(__name__)


@router.post(
    "/",
    response_model=ContactRequestRead,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit(settings.contact_request_rate_limit)
async def create_contact_request(
    request: Request,
    payload: ContactRequestCreate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ContactRequest:
    entry = ContactRequest(**payload.model_dump())
    session.add(entry)
    await session.flush()

    await record_action(
        session,
        user_id=None,
        action="contact_request_submitted",
        resource_type="ContactRequest",
        resource_id=str(entry.id),
        changes={"email": entry.email},
        request=request,
    )

    # Fire-and-forget notification to admins via email-service.
    from app.workers.actors import notify_admins_on_contact_request

    notify_admins_on_contact_request.send(entry.id)
    log.info("contact_request_submitted", id=entry.id, email=entry.email)
    return entry


@router.get("/", response_model=list[ContactRequestRead])
async def list_contact_requests(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _admin: Annotated[TokenPayload, Depends(require_admin)],
    handled: Optional[bool] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[ContactRequest]:
    stmt = select(ContactRequest).order_by(ContactRequest.created_at.desc())
    if handled is not None:
        stmt = stmt.where(ContactRequest.handled.is_(handled))
    stmt = stmt.limit(limit).offset(offset)
    result = await session.execute(stmt)
    return list(result.scalars().all())


@router.get("/stats", response_model=ContactRequestStats)
@router.get("/stats/", response_model=ContactRequestStats, include_in_schema=False)
async def contact_request_stats(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _admin: Annotated[TokenPayload, Depends(require_admin)],
) -> ContactRequestStats:
    """Unhandled contact-request count for the admin badge.

    Frontend (`ProfileSidebar.tsx`) calls this with a trailing slash;
    we register both forms to avoid the 307 redirect that breaks the
    Authorization header on some browsers.
    """
    stmt = select(func.count()).select_from(ContactRequest).where(ContactRequest.handled.is_(False))
    count = (await session.execute(stmt)).scalar_one()
    return ContactRequestStats(unhandled=count)


@router.get("/{contact_id}", response_model=ContactRequestRead)
async def get_contact_request(
    contact_id: int,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _admin: Annotated[TokenPayload, Depends(require_admin)],
) -> ContactRequest:
    entry = await session.get(ContactRequest, contact_id)
    if not entry:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contact request not found")
    return entry


@router.patch("/{contact_id}", response_model=ContactRequestRead)
async def update_contact_request(
    contact_id: int,
    payload: ContactRequestUpdate,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    admin: Annotated[TokenPayload, Depends(require_admin)],
) -> ContactRequest:
    entry = await session.get(ContactRequest, contact_id)
    if not entry:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contact request not found")

    changes = payload.model_dump(exclude_unset=True)
    for key, value in changes.items():
        setattr(entry, key, value)
    await session.flush()

    await record_action(
        session,
        user_id=admin.user_id,
        action="contact_request_updated",
        resource_type="ContactRequest",
        resource_id=str(entry.id),
        changes=changes,
        request=request,
    )
    return entry


@router.post("/{contact_id}/reply", response_model=ContactRequestRead)
async def reply_contact_request(
    contact_id: int,
    payload: ContactRequestReply,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    admin: Annotated[TokenPayload, Depends(require_admin)],
) -> ContactRequest:
    entry = await session.get(ContactRequest, contact_id)
    if not entry:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contact request not found")

    entry.reply_message = payload.reply_message
    entry.replied_at = datetime.now(timezone.utc)
    entry.replied_by_id = admin.user_id
    entry.handled = True
    await session.flush()

    await record_action(
        session,
        user_id=admin.user_id,
        action="contact_request_replied",
        resource_type="ContactRequest",
        resource_id=str(entry.id),
        changes={"reply_message": payload.reply_message},
        request=request,
    )
    log.info("contact_request_replied", id=entry.id, by=admin.user_id)
    return entry


@router.delete("/{contact_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_contact_request(
    contact_id: int,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    admin: Annotated[TokenPayload, Depends(require_admin)],
) -> None:
    entry = await session.get(ContactRequest, contact_id)
    if not entry:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contact request not found")
    email = entry.email
    await session.delete(entry)
    await record_action(
        session,
        user_id=admin.user_id,
        action="contact_request_deleted",
        resource_type="ContactRequest",
        resource_id=str(contact_id),
        changes={"email": email},
        request=request,
    )
