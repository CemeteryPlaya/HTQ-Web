"""Admin API for Mailcow-backed mailbox provisioning.

All endpoints require staff or superuser. Service-to-service callers
(user-service hook on POST /admin/users/) authenticate with the same JWT —
that's why we accept either user JWT (with is_staff) or a service JWT
(claim ``service=True``).

Routes (mounted under /api/email/v1):
    GET    /mailboxes/                     — list (admin UI table)
    POST   /mailboxes/                     — create (admin or S2S)
    GET    /mailboxes/{id}/                — single row
    PATCH  /mailboxes/{id}/                — rename / quota
    POST   /mailboxes/{id}/reset-password/ — admin-set new password
    POST   /mailboxes/{id}/archive/        — stage-1 of delete (active=0)
    POST   /mailboxes/{id}/restore/        — undo archive
    DELETE /mailboxes/{id}/                — stage-2 (only if archived)

    GET    /mailboxes/aliases/             — list all aliases for our domain
    POST   /mailboxes/aliases/             — create alias
    DELETE /mailboxes/aliases/{alias_id}/  — delete alias
    POST   /mailboxes/{id}/forwarding/     — set forward-to on a mailbox
"""

from __future__ import annotations

from typing import Annotated

import jwt
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import TokenPayload
from app.core.settings import settings
from app.db import get_db_session
from app.schemas.mailbox import (
    AliasCreateRequest,
    ForwardingSetRequest,
    MailboxCreatedResponse,
    MailboxCreateRequest,
    MailboxOut,
    MailboxResetPasswordRequest,
    MailboxUpdateRequest,
)
from app.services.mailbox_service import MailboxService
from app.services.mailcow_client import MailcowClient


log = structlog.get_logger(__name__)

router = APIRouter(prefix="/mailboxes", tags=["mailboxes"])
security = HTTPBearer(auto_error=True)


# ── Auth: accept either user-JWT (admin) or service-JWT (S2S) ───────────────

def require_mailbox_admin(
    auth: Annotated[HTTPAuthorizationCredentials, Depends(security)],
    request: Request,
) -> TokenPayload:
    """Validate either a user admin JWT (is_staff/is_superuser) or a service JWT.

    Service JWTs carry ``service=True`` and are signed with SERVICE_JWT_SECRET;
    this is how user-service hooks call us when an admin creates a new user.
    """
    token = auth.credentials
    # Try user JWT first.
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            issuer=settings.jwt_issuer,
            options={"verify_exp": True},
        )
        tp = TokenPayload(**payload)
        if tp.is_staff or tp.is_superuser or tp.is_admin:
            return tp
    except jwt.PyJWTError:
        pass

    # Fall back to S2S service JWT.
    try:
        payload = jwt.decode(
            token,
            settings.service_jwt_secret,
            algorithms=[settings.service_jwt_algorithm],
            options={"verify_exp": True, "verify_iss": False},
        )
        if payload.get("service") is True:
            return TokenPayload(
                user_id=payload.get("user_id", 0),
                is_staff=True,
                is_superuser=False,
                exp=payload.get("exp", 0),
            )
    except jwt.PyJWTError:
        pass

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Admin or service token required",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _svc(db: AsyncSession = Depends(get_db_session)) -> MailboxService:
    return MailboxService(db)


# ── Mailbox CRUD ────────────────────────────────────────────────────────────


@router.get("/", response_model=list[MailboxOut])
async def list_mailboxes(
    include_deleted: bool = False,
    svc: MailboxService = Depends(_svc),
    _: TokenPayload = Depends(require_mailbox_admin),
):
    return await svc.list_mailboxes(include_deleted=include_deleted)


@router.post("/", response_model=MailboxCreatedResponse, status_code=201)
async def create_mailbox(
    payload: MailboxCreateRequest,
    svc: MailboxService = Depends(_svc),
    _: TokenPayload = Depends(require_mailbox_admin),
):
    mb, generated_password = await svc.create(payload)
    return MailboxCreatedResponse(
        **MailboxOut.model_validate(mb).model_dump(),
        generated_password=generated_password,
    )


@router.get("/{mailbox_id}/", response_model=MailboxOut)
async def get_mailbox(
    mailbox_id: int,
    svc: MailboxService = Depends(_svc),
    _: TokenPayload = Depends(require_mailbox_admin),
):
    return await svc.get_by_id(mailbox_id)


@router.patch("/{mailbox_id}/", response_model=MailboxOut)
async def update_mailbox(
    mailbox_id: int,
    payload: MailboxUpdateRequest,
    svc: MailboxService = Depends(_svc),
    _: TokenPayload = Depends(require_mailbox_admin),
):
    return await svc.update(mailbox_id, payload)


@router.post("/{mailbox_id}/reset-password/", response_model=MailboxCreatedResponse)
async def reset_mailbox_password(
    mailbox_id: int,
    payload: MailboxResetPasswordRequest,
    svc: MailboxService = Depends(_svc),
    _: TokenPayload = Depends(require_mailbox_admin),
):
    mb, generated_password = await svc.reset_password(mailbox_id, payload)
    return MailboxCreatedResponse(
        **MailboxOut.model_validate(mb).model_dump(),
        generated_password=generated_password,
    )


@router.post("/{mailbox_id}/archive/", response_model=MailboxOut)
async def archive_mailbox(
    mailbox_id: int,
    svc: MailboxService = Depends(_svc),
    _: TokenPayload = Depends(require_mailbox_admin),
):
    return await svc.archive(mailbox_id)


@router.post("/{mailbox_id}/restore/", response_model=MailboxOut)
async def restore_mailbox(
    mailbox_id: int,
    svc: MailboxService = Depends(_svc),
    _: TokenPayload = Depends(require_mailbox_admin),
):
    return await svc.restore(mailbox_id)


@router.delete("/{mailbox_id}/", status_code=204)
async def delete_mailbox(
    mailbox_id: int,
    svc: MailboxService = Depends(_svc),
    _: TokenPayload = Depends(require_mailbox_admin),
):
    """Stage 2 — only allowed if mailbox is currently in `archived` state."""
    await svc.delete(mailbox_id)


# ── Aliases (proxied to Mailcow live; not mirrored locally) ─────────────────


@router.get("/aliases/")
async def list_aliases(
    _: TokenPayload = Depends(require_mailbox_admin),
):
    try:
        return await MailcowClient().list_aliases()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Mailcow error: {exc}") from exc


@router.post("/aliases/", status_code=201)
async def create_alias(
    payload: AliasCreateRequest,
    _: TokenPayload = Depends(require_mailbox_admin),
):
    try:
        return await MailcowClient().add_alias(
            address=str(payload.address), goto=payload.goto, active=payload.active,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Mailcow error: {exc}") from exc


@router.delete("/aliases/{alias_id}/", status_code=204)
async def delete_alias(
    alias_id: int,
    _: TokenPayload = Depends(require_mailbox_admin),
):
    try:
        await MailcowClient().delete_alias(alias_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Mailcow error: {exc}") from exc


# ── Forwarding ──────────────────────────────────────────────────────────────


@router.post("/{mailbox_id}/forwarding/", status_code=201)
async def set_forwarding(
    mailbox_id: int,
    payload: ForwardingSetRequest,
    svc: MailboxService = Depends(_svc),
    _: TokenPayload = Depends(require_mailbox_admin),
):
    mb = await svc.get_by_id(mailbox_id)
    try:
        return await MailcowClient().set_forwarding(
            mb.address, str(payload.forward_to), keep_local_copy=payload.keep_local_copy,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Mailcow error: {exc}") from exc
