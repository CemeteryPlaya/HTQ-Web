"""Unified account management — corporate (Mailcow) + personal (OAuth).

The frontend account selector (`<AccountSelector/>`) loads everything from
``GET /accounts/``; switching the active tab and choosing a default sender
both go through this router. OAuth-specific connect/callback flows still
live in ``oauth.py`` (rewritten in phase 3).
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

import logging

from app.auth.dependencies import TokenPayload, get_current_user
from app.db import get_db_session
from app.models.account import EmailAccount
from app.models.email import EmailMessage, OAuthToken
from app.schemas.account import EmailAccountRead, EmailAccountSyncResponse
from app.services.crypto import crypto_service
from app.services.oauth_clients import get_oauth_client


log = logging.getLogger(__name__)


router = APIRouter(tags=["accounts"])


@router.get("/", response_model=list[EmailAccountRead])
async def list_accounts(
    session: AsyncSession = Depends(get_db_session),
    user: TokenPayload = Depends(get_current_user),
) -> list[EmailAccountRead]:
    """Return every linked mailbox/OAuth identity for the current user."""
    unread_subq = (
        select(func.count(EmailMessage.id))
        .where(
            EmailMessage.account_id == EmailAccount.id,
            EmailMessage.folder == "inbox",
            EmailMessage.is_read.is_(False),
        )
        .correlate(EmailAccount)
        .scalar_subquery()
    )

    stmt = (
        select(EmailAccount, unread_subq.label("unread_count"))
        .where(EmailAccount.user_id == user.user_id)
        .order_by(EmailAccount.is_default.desc(), EmailAccount.id.asc())
    )
    rows = (await session.execute(stmt)).all()

    out: list[EmailAccountRead] = []
    for account, unread in rows:
        item = EmailAccountRead.model_validate(account)
        item.unread_count = unread or 0
        out.append(item)
    return out


@router.post("/{account_id}/set-default/", response_model=EmailAccountRead)
async def set_default_account(
    account_id: int,
    session: AsyncSession = Depends(get_db_session),
    user: TokenPayload = Depends(get_current_user),
) -> EmailAccountRead:
    """Mark this account as the compose-default. Atomic per user."""
    account = await session.get(EmailAccount, account_id)
    if account is None or account.user_id != user.user_id:
        raise HTTPException(status_code=404, detail="Account not found")

    # Reset all defaults for this user, then set the chosen one.
    await session.execute(
        update(EmailAccount)
        .where(EmailAccount.user_id == user.user_id, EmailAccount.is_default.is_(True))
        .values(is_default=False)
    )
    account.is_default = True
    await session.commit()
    await session.refresh(account)
    return EmailAccountRead.model_validate(account)


@router.post(
    "/{account_id}/sync/",
    response_model=EmailAccountSyncResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def trigger_account_sync(
    account_id: int,
    session: AsyncSession = Depends(get_db_session),
    user: TokenPayload = Depends(get_current_user),
) -> EmailAccountSyncResponse:
    """Queue an incremental sync. Implementation lands in phase 4."""
    account = await session.get(EmailAccount, account_id)
    if account is None or account.user_id != user.user_id:
        raise HTTPException(status_code=404, detail="Account not found")
    if not account.is_active:
        raise HTTPException(status_code=409, detail="Account is inactive")

    from app.workers.sync_actors import incremental_sync_account
    incremental_sync_account.send(account_id)
    return EmailAccountSyncResponse(
        account_id=account_id,
        queued_at=datetime.now(timezone.utc),
        status="queued",
    )


@router.delete("/{account_id}/", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect_account(
    account_id: int,
    session: AsyncSession = Depends(get_db_session),
    user: TokenPayload = Depends(get_current_user),
) -> None:
    """Disconnect a personal OAuth account.

    Corporate (Mailcow) accounts must go through
    ``POST /api/email/v1/mailboxes/{id}/archive/`` so the two-stage delete
    flow stays under admin control.
    """
    account = await session.get(EmailAccount, account_id)
    if account is None or account.user_id != user.user_id:
        raise HTTPException(status_code=404, detail="Account not found")
    if account.type == "corporate":
        raise HTTPException(
            status_code=400,
            detail="Corporate mailboxes are removed via /mailboxes/{id}/archive/",
        )

    if account.oauth_token_id is not None:
        token_row = await session.get(OAuthToken, account.oauth_token_id)
        if token_row is not None:
            try:
                client = get_oauth_client(account.provider)
                access = crypto_service.decrypt(token_row.encrypted_access_token)
                await client.revoke(access)
            except Exception as exc:  # best-effort
                log.warning("oauth_revoke_failed: %s", exc)
        await session.execute(
            delete(OAuthToken).where(OAuthToken.id == account.oauth_token_id)
        )
    await session.execute(delete(EmailAccount).where(EmailAccount.id == account.id))
    await session.commit()
