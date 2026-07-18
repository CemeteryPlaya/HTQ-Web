"""Shareable links API — authenticated management endpoints.

Token security:
- POST returns the raw token + ready-to-use URL exactly once. The raw token is
  never persisted server-side (only SHA-256(token) lives in the DB).
- GET / GET /{id} never expose any token material.
"""

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import TokenPayload, get_current_user
from app.core.settings import settings
from app.db import get_db_session
from app.services.share_link_service import ShareLinkService

router = APIRouter(prefix="/share-links", tags=["share-links"])


def _svc(db: AsyncSession = Depends(get_db_session)) -> ShareLinkService:
    return ShareLinkService(db)


# ── Schemas ────────────────────────────────────────────────────────────


class LinkCreate(BaseModel):
    label: str | None = Field(default=None, max_length=200)
    viewer_label: str | None = Field(default=None, max_length=64)
    watermark_text: str | None = Field(default=None, max_length=128)
    max_level: int = Field(default=3, ge=1, le=10)
    default_language: Literal["ru", "en"] = "ru"
    visible_units: list[int] | None = None
    link_type: Literal["one_time", "time_limited", "permanent_with_expiry"] = "one_time"
    expires_at: datetime | None = None
    # When ``target_type='employee'``, ``target_employee_id`` must be set; the
    # public consume endpoint is then ``/public/employee/{token}``.
    target_type: Literal["org", "employee"] = "org"
    target_employee_id: int | None = None


class LinkOut(BaseModel):
    """List/detail view — no token material, ever."""

    id: uuid.UUID
    label: str | None
    viewer_label: str | None
    watermark_text: str | None
    max_level: int
    default_language: str
    link_type: str
    expires_at: datetime | None
    opened_at: datetime | None
    used_at: datetime | None
    revoked_at: datetime | None
    is_active: bool
    created_at: datetime
    target_type: str = "org"
    target_employee_id: int | None = None

    model_config = ConfigDict(from_attributes=True)


class LinkCreatedOut(LinkOut):
    """POST response — includes the raw token and a fully-formed public URL.

    This is the *only* response shape that ever carries `token`/`url`.
    """

    token: str
    url: str


class AuditEntryOut(BaseModel):
    id: int
    action: str
    occurred_at: datetime
    ip: str | None
    user_agent: str | None
    reason: str | None

    model_config = ConfigDict(from_attributes=True)


def _public_path_for(target_type: str) -> str:
    return "/public/employee/" if target_type == "employee" else "/public/org/"


def _public_url(request: Request, raw_token: str, target_type: str = "org") -> str:
    """Build the user-facing public URL.

    Resolution order:
    1. ``settings.public_base_url`` if configured (prod canonical host).
    2. ``X-Forwarded-Host`` / ``X-Forwarded-Proto`` set by a reverse proxy.
    3. Fallback to ``request.url.{scheme,netloc}`` — last resort, may point
       at the API host instead of the frontend in dev with proxy rewriting.

    The frontend additionally rebuilds the URL from ``window.location.origin``
    on display, which makes the value here mostly informational.
    """
    path = _public_path_for(target_type)
    base = getattr(settings, "public_base_url", None)
    if base:
        return f"{base.rstrip('/')}{path}{raw_token}"

    fwd_host = request.headers.get("x-forwarded-host", "").split(",")[0].strip()
    if fwd_host:
        proto = request.headers.get("x-forwarded-proto", request.url.scheme).split(",")[0].strip()
        return f"{proto}://{fwd_host}{path}{raw_token}"

    return f"{request.url.scheme}://{request.url.netloc}{path}{raw_token}"


# ── Routes ─────────────────────────────────────────────────────────────


@router.post("/", response_model=LinkCreatedOut, status_code=status.HTTP_201_CREATED)
async def create_link(
    body: LinkCreate,
    request: Request,
    svc: ShareLinkService = Depends(_svc),
    current_user: TokenPayload = Depends(get_current_user),
):
    created = await svc.create_link(current_user.user_id, body.model_dump())
    out = LinkOut.model_validate(created.link).model_dump()
    return LinkCreatedOut(
        **out,
        token=created.raw_token,
        url=_public_url(request, created.raw_token, created.link.target_type or "org"),
    )


@router.get("/", response_model=list[LinkOut])
async def list_links(
    svc: ShareLinkService = Depends(_svc),
    current_user: TokenPayload = Depends(get_current_user),
):
    return await svc.list_links(current_user.user_id)


@router.delete("/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_link(
    link_id: uuid.UUID,
    svc: ShareLinkService = Depends(_svc),
    current_user: TokenPayload = Depends(get_current_user),
):
    await svc.revoke_link(link_id, current_user.user_id)


@router.get("/{link_id}/audit", response_model=list[AuditEntryOut])
async def link_audit(
    link_id: uuid.UUID,
    svc: ShareLinkService = Depends(_svc),
    current_user: TokenPayload = Depends(get_current_user),
):
    """Forensic trail for a single link. Owner-only."""
    return await svc.list_audit(link_id, current_user.user_id)
