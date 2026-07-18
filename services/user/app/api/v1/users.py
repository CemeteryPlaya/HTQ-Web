"""Non-admin user listing — drives any "pick a colleague" picker.

Existing ``/api/users/v1/admin/users/`` requires admin and returns a heavy
payload. For things like the calendar event participants picker any
authenticated user should be able to see who else exists, with the minimal
shape ``{id, full_name, email}``.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import or_, select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.db import get_db_session
from app.models.user import User, UserStatus


router = APIRouter(prefix="/api/users/v1/users", tags=["users"])


class UserOption(BaseModel):
    id: int
    full_name: str
    email: str


@router.get("/options/", response_model=list[UserOption])
async def list_user_options(
    db: Annotated[AsyncSession, Depends(get_db_session)],
    current_user=Depends(get_current_user),
    query: str | None = Query(default=None, description="Optional substring filter"),
    limit: int = Query(default=200, ge=1, le=500),
):
    """Return active users compacted for picker UIs.

    Any authenticated user can call this. Result excludes suspended /
    pending / rejected accounts. ``query`` filters case-insensitively
    across first/last name, email and username.
    """
    stmt = select(User).where(User.status == UserStatus.ACTIVE)
    if query:
        like = f"%{query.lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(User.first_name).like(like),
                func.lower(User.last_name).like(like),
                func.lower(User.email).like(like),
                func.lower(User.username).like(like),
                func.lower(User.display_name).like(like),
            )
        )
    stmt = stmt.order_by(User.last_name.asc(), User.first_name.asc()).limit(limit)
    result = await db.execute(stmt)
    users = list(result.scalars().all())
    out: list[UserOption] = []
    for u in users:
        full_name = (
            f"{u.first_name} {u.last_name}".strip()
            or u.display_name
            or u.username
        )
        out.append(UserOption(id=u.id, full_name=full_name, email=u.email or ""))
    return out
