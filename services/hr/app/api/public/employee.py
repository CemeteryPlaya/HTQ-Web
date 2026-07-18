"""Public employee-card endpoint — no auth, accessed via shareable token.

Mirrors ``api.public.org``: consumed via ``/api/hr/v1/public/employee/{token}``,
rate-limited 10/minute per IP, X-Robots-Tag noindex. The ``ShareLinkService``
strips PII before returning, so a leaked token never exposes contact data
that wasn't already in the card preview.
"""

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.public.org import limiter
from app.db import get_db_session
from app.services.share_link_service import ShareLinkService

router = APIRouter(prefix="/public/employee", tags=["public"])


def _svc(db: AsyncSession = Depends(get_db_session)) -> ShareLinkService:
    return ShareLinkService(db)


@router.get("/{token}")
@limiter.limit("10/minute")
async def view_public_employee(
    token: str,
    request: Request,
    response: Response,
    svc: ShareLinkService = Depends(_svc),
):
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    response.headers["Cache-Control"] = "no-store"
    return await svc.consume_employee_link(token, request)
