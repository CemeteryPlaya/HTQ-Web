"""Public org endpoint — no authentication, accessed via shareable token.

Rate limiting: 10 requests/minute per IP via slowapi.
Response: X-Robots-Tag: noindex to prevent search indexing.
"""

from fastapi import APIRouter, Depends, Request, Response
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db_session
from app.services.share_link_service import ShareLinkService

limiter = Limiter(key_func=get_remote_address)

router = APIRouter(prefix="/public/org", tags=["public"])


def _svc(db: AsyncSession = Depends(get_db_session)) -> ShareLinkService:
    return ShareLinkService(db)


@router.get("/{token}")
@limiter.limit("10/minute")
async def view_public_org(
    token: str,
    request: Request,
    response: Response,
    svc: ShareLinkService = Depends(_svc),
):
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    response.headers["Cache-Control"] = "no-store"
    return await svc.consume_link(token, request)
