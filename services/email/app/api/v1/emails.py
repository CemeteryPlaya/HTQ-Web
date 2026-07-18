"""Email API endpoints."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel as _Base
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import TokenPayload, get_current_user
from app.db import get_db_session
from app.models.account import EmailAccount
from app.models.email import EmailMessage, RecipientStatus
from app.schemas.email import EmailMessageRead, EmailMessageDetail, EmailSendRequest
from app.services.dlp_scanner import dlp_scanner

router = APIRouter(tags=["emails"])


VALID_FOLDERS = {"inbox", "sent", "drafts", "trash", "archive", "spam", "outbox"}


@router.get("/folder/{folder}", response_model=list[EmailMessageRead])
async def list_emails(
    folder: str,
    session: AsyncSession = Depends(get_db_session),
    user: TokenPayload = Depends(get_current_user),
    account_id: int | None = Query(None, description="Limit to one account; omit for unified view"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """List emails in a folder.

    With ``account_id`` → that account only (covers the per-account tab in
    the UI). Without it → unified inbox across every linked account the
    current user owns.
    """
    if folder not in VALID_FOLDERS:
        raise HTTPException(status_code=400, detail="Invalid folder")

    stmt = (
        select(EmailMessage)
        .where(EmailMessage.user_id == user.user_id, EmailMessage.folder == folder)
        .order_by(EmailMessage.date.desc())
        .limit(limit)
        .offset(offset)
    )
    if account_id is not None:
        stmt = stmt.where(EmailMessage.account_id == account_id)
    result = await session.execute(stmt)
    return list(result.scalars().all())


@router.get("/unread-counts/")
async def unread_counts(
    session: AsyncSession = Depends(get_db_session),
    user: TokenPayload = Depends(get_current_user),
) -> dict:
    """Return ``{by_account: {id: n}, by_folder: {name: n}}`` for the user.

    Used by the sidebar badges so the UI can render unread counts both
    per-folder (Inbox 3) and per-account in one shot.
    """
    by_account_rows = await session.execute(
        select(EmailMessage.account_id, func.count(EmailMessage.id))
        .where(
            EmailMessage.user_id == user.user_id,
            EmailMessage.folder == "inbox",
            EmailMessage.is_read.is_(False),
            EmailMessage.account_id.is_not(None),
        )
        .group_by(EmailMessage.account_id)
    )
    by_account = {int(aid): int(n) for aid, n in by_account_rows.all()}

    by_folder_rows = await session.execute(
        select(EmailMessage.folder, func.count(EmailMessage.id))
        .where(
            EmailMessage.user_id == user.user_id,
            EmailMessage.is_read.is_(False),
        )
        .group_by(EmailMessage.folder)
    )
    by_folder = {str(f): int(n) for f, n in by_folder_rows.all()}

    return {"by_account": by_account, "by_folder": by_folder}


@router.get("/{message_id}", response_model=EmailMessageDetail)
async def get_email(
    message_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    user: TokenPayload = Depends(get_current_user),
):
    """Get full email details."""
    stmt = select(EmailMessage).where(EmailMessage.id == message_id, EmailMessage.user_id == user.user_id)
    result = await session.execute(stmt)
    msg = result.scalar_one_or_none()
    if not msg:
        raise HTTPException(status_code=404, detail="Email not found")
    
    # Optional: fetch attachments if needed (not fully joined here for simplicity)
    return msg


@router.post("/send", status_code=status.HTTP_202_ACCEPTED)
async def send_email(
    data: EmailSendRequest,
    session: AsyncSession = Depends(get_db_session),
    user: TokenPayload = Depends(get_current_user),
):
    """Queue an outbound message for delivery via the user's chosen account."""
    account = await session.get(EmailAccount, data.account_id)
    if account is None or account.user_id != user.user_id:
        raise HTTPException(status_code=404, detail="Account not found")
    if not account.is_active:
        raise HTTPException(status_code=409, detail="Account is inactive")

    # DLP scan over user-provided fields only.
    content = (data.subject or "") + " " + (data.body_text or "") + " " + (data.body_html or "")
    if dlp_scanner.scan(content):
        raise HTTPException(
            status_code=403,
            detail="DLP Policy Violation: Sensitive data detected.",
        )

    import datetime
    msg = EmailMessage(
        user_id=user.user_id,
        account_id=account.id,
        folder="outbox",
        subject=data.subject or "",
        snippet=(data.subject or "")[:255],
        body_html=data.body_html,
        body_text=data.body_text,
        sender_email=account.address,
        sender_name=account.display_name,
        to_recipients=data.to_recipients,
        cc_recipients=data.cc_recipients,
        bcc_recipients=data.bcc_recipients,
        is_read=True,  # outbound messages are always read by sender
        date=datetime.datetime.now(datetime.timezone.utc),
    )
    session.add(msg)
    await session.flush()

    # Track per-recipient delivery status.
    for r in (data.to_recipients or []) + (data.cc_recipients or []) + (data.bcc_recipients or []):
        addr = r.get("email") if isinstance(r, dict) else None
        if not addr:
            continue
        session.add(
            RecipientStatus(
                message_id=msg.id,
                recipient_email=addr,
                status="pending",
            )
        )
    await session.commit()
    await session.refresh(msg)

    # Async delivery — picked up by deliver_email actor.
    from app.workers.actors import deliver_email
    deliver_email.send(str(msg.id))

    return {"status": "queued", "id": str(msg.id)}


@router.post("/{message_id}/read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_as_read(
    message_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    user: TokenPayload = Depends(get_current_user),
):
    """Mark email as read."""
    stmt = update(EmailMessage).where(
        EmailMessage.id == message_id, EmailMessage.user_id == user.user_id
    ).values(is_read=True)
    await session.execute(stmt)
    await session.commit()


# ─── Drafts (frontend posts to /draft) ────────────────────────────────


class DraftIn(_Base):
    subject: str = ""
    body: str = ""


@router.post("/draft", status_code=status.HTTP_201_CREATED)
async def save_draft(
    data: DraftIn,
    session: AsyncSession = Depends(get_db_session),
    user: TokenPayload = Depends(get_current_user),
):
    """Persist a draft message in the user's drafts folder.

    Minimal stub — no MTA call, no recipients. Lives so the SPA's compose
    modal "Save draft" button doesn't 404.
    """
    import datetime as _dt
    msg = EmailMessage(
        user_id=user.user_id,
        account_id=None,
        folder="drafts",
        subject=data.subject or "",
        snippet=(data.subject or "")[:100],
        body_text=data.body or "",
        body_html="",
        sender_email="",
        to_recipients=[],
        cc_recipients=[],
        bcc_recipients=[],
        date=_dt.datetime.now(_dt.timezone.utc),
    )
    session.add(msg)
    await session.commit()
    await session.refresh(msg)
    return {"id": str(msg.id), "folder": "drafts"}
