"""S2S endpoints — accessed only by other internal services via shared secret."""

import os
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field

from app.services.system_bots import (
    BOT_CALENDAR, BOT_EMAIL, BOT_FILES, BOT_NEWS, BOT_REQUESTS, BOT_TASKS,
    SystemBot, post_bot_message,
)

router = APIRouter(tags=["internal"])

_BY_USERNAME: dict[str, SystemBot] = {
    b.username: b for b in (BOT_CALENDAR, BOT_TASKS, BOT_EMAIL, BOT_FILES, BOT_NEWS, BOT_REQUESTS)
}


class BotMessageRequest(BaseModel):
    bot: str = Field(..., description="Bot username, e.g. 'bot-requests'")
    user_id: int
    text: str = Field(..., min_length=1, max_length=4000)
    metadata: dict[str, Any] | None = None


async def require_internal_token(x_internal_token: Annotated[str | None, Header()] = None) -> None:
    expected = os.environ.get("MESSENGER_INTERNAL_TOKEN") or ""
    if not expected:
        raise HTTPException(status_code=503, detail="MESSENGER_INTERNAL_TOKEN not configured")
    if not x_internal_token or x_internal_token != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid internal token")


@router.post("/bot-message", status_code=202, dependencies=[Depends(require_internal_token)])
async def send_bot_message_endpoint(payload: BotMessageRequest):
    bot = _BY_USERNAME.get(payload.bot)
    if bot is None:
        raise HTTPException(status_code=400, detail=f"unknown bot '{payload.bot}'")
    msg = await post_bot_message(
        user_id=payload.user_id, bot=bot, text=payload.text, metadata=payload.metadata,
    )
    return {"delivered": msg is not None, "message_id": str(msg.id) if msg else None}
