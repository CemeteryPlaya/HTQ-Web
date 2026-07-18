"""E2EE Keys API endpoints."""


from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import TokenPayload, get_current_user
from app.db import get_db_session
from app.models.domain import UserKey
from app.schemas.messenger import UserKeyCreate, UserKeyRead

router = APIRouter(tags=["keys"])


@router.post("/", response_model=UserKeyRead, status_code=status.HTTP_201_CREATED)
async def upload_keys(
    data: UserKeyCreate,
    session: AsyncSession = Depends(get_db_session),
    user: TokenPayload = Depends(get_current_user),
):
    """Upload public keys for a device."""
    key = await session.get(UserKey, (user.user_id, data.device_id))
    if key:
        # Update existing keys
        key.public_identity_key = data.public_identity_key
        key.signed_pre_key = data.signed_pre_key
        key.signature = data.signature
    else:
        # Create new keys
        key = UserKey(
            user_id=user.user_id,
            device_id=data.device_id,
            public_identity_key=data.public_identity_key,
            signed_pre_key=data.signed_pre_key,
            signature=data.signature,
        )
        session.add(key)

    await session.commit()
    await session.refresh(key)
    return key


@router.get("/{user_id}", response_model=list[UserKeyRead])
async def get_user_keys(
    user_id: int,
    session: AsyncSession = Depends(get_db_session),
    user: TokenPayload = Depends(get_current_user),
):
    """Get public keys for all devices of a user."""
    stmt = select(UserKey).where(UserKey.user_id == user_id)
    result = await session.execute(stmt)
    return list(result.scalars().all())
