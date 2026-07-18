"""Server-Sent Events endpoint for real-time request updates.

Browsers' ``EventSource`` API can't set custom headers, so we accept the JWT
via a ``?token=...`` query parameter in addition to the standard
``Authorization: Bearer …`` header."""

import asyncio
import json
import logging
from typing import Annotated

import jwt
import redis.asyncio as aioredis
from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse

from app.core.settings import settings

router = APIRouter(tags=["stream"])
log = logging.getLogger(__name__)

_HEARTBEAT_SECONDS = 25.0


def _decode_token(token: str) -> int:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            issuer=settings.jwt_issuer,
            options={"verify_exp": True},
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"invalid token: {exc}")
    uid = payload.get("user_id")
    if not isinstance(uid, int):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="token missing user_id")
    return uid


def _extract_token(request: Request, token_qs: str | None) -> str:
    if token_qs:
        return token_qs
    auth = request.headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth.split(None, 1)[1].strip()
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing token")


@router.get("/stream")
async def stream(
    request: Request,
    token: Annotated[str | None, Query()] = None,
):
    """Open a Server-Sent Events stream for the authenticated user.

    Emits one SSE event per dispatched notification (request_assigned,
    approved_partial, approved_final, rejected, request_changes, cancelled),
    plus periodic ``:heartbeat`` comments so reverse proxies don't kill the
    connection on idle."""
    raw = _extract_token(request, token)
    user_id = _decode_token(raw)
    channel = f"requests:user:{user_id}"

    async def event_stream():
        client = aioredis.Redis.from_url(settings.redis_url)
        pubsub = client.pubsub()
        await pubsub.subscribe(channel)
        try:
            # Open the SSE handshake — some clients ignore the response until
            # the first chunk arrives.
            yield ": connected\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(
                        pubsub.get_message(ignore_subscribe_messages=True, timeout=None),
                        timeout=_HEARTBEAT_SECONDS,
                    )
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
                    continue
                if msg is None or msg.get("type") != "message":
                    continue
                raw_data = msg.get("data") or b""
                if isinstance(raw_data, bytes):
                    raw_data = raw_data.decode("utf-8", errors="replace")
                try:
                    parsed = json.loads(raw_data)
                except (ValueError, TypeError):
                    continue
                event_name = parsed.get("event", "message")
                # SSE event names cannot contain newlines/colons in the value.
                event_name = str(event_name).replace("\n", " ").replace(":", "_")
                yield f"event: {event_name}\ndata: {raw_data}\n\n"
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.warning("sse_stream_error user=%s err=%s", user_id, exc)
        finally:
            try:
                await pubsub.unsubscribe(channel)
                await pubsub.aclose()
                await client.aclose()
            except Exception:  # noqa: BLE001
                pass

    headers = {
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",  # signal to nginx
        "Connection": "keep-alive",
    }
    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=headers)
