"""Socket.IO server — real-time messenger transport.

Frontend client lives in `frontend/src/features/messenger/api/socket.ts` and
connects with `path: /ws/messenger/socket.io` and `auth: { token: <JWT> }`.

Event protocol (matches `useMessengerSocket.ts`):

  Server → Client:
    - message_new   {room_id, message}        : when a peer sends a message
    - message_read  {room_id, message_id, reader_user_id}
    - user_typing   {room_id, user_id, is_typing}

  Client → Server:
    - join_room   {room_id}                   : after auth, before the user
                                                 should receive room events
    - leave_room  {room_id}
    - typing      {room_id, is_typing}
    - mark_read   {room_id, message_id}       : optional WS-side alternative
                                                 to POST /messages/.../read

Authorization: each connection MUST attach a JWT in `auth.token` (or the
`token` query string, as a fallback for clients that can't set auth dict).
We refuse the connection on missing/invalid/non-admin-or-user JWTs.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs

import jwt
import socketio
from sqlalchemy import select

from app.core.logging import get_logger
from app.core.settings import settings
from app.db import async_session_factory
from app.models.domain import RoomParticipant


log = get_logger(__name__)


# Configure Socket.IO with Redis Manager so multiple messenger replicas can
# fan-out events to the right rooms without each holding the full subscriber
# graph in process memory.
mgr = socketio.AsyncRedisManager(settings.redis_url)

sio = socketio.AsyncServer(
    async_mode="asgi",
    cors_allowed_origins="*",
    client_manager=mgr,
)

# Starlette's Mount sets `root_path` but does NOT rewrite `scope["path"]`,
# while engineio's ASGIApp matches against the raw `scope["path"]`. So we
# bake the mount prefix into `socketio_path` and mount at the FastAPI root.
sio_app = socketio.ASGIApp(
    socketio_server=sio,
    socketio_path="/ws/messenger/socket.io",
)


def _extract_token(auth: dict[str, Any] | None, environ: dict[str, Any]) -> str | None:
    """Pull JWT from auth dict, query string, or Authorization header."""
    if auth and isinstance(auth, dict):
        token = auth.get("token") or auth.get("jwt")
        if token:
            return str(token)

    qs = environ.get("QUERY_STRING") or ""
    if qs:
        params = parse_qs(qs)
        for key in ("token", "jwt", "access_token"):
            if params.get(key):
                return params[key][0]

    auth_header = environ.get("HTTP_AUTHORIZATION") or ""
    if auth_header.lower().startswith("bearer "):
        return auth_header.split(" ", 1)[1].strip() or None
    return None


def _decode_jwt(token: str) -> dict[str, Any]:
    """Decode + validate a platform JWT. Raises ConnectionRefusedError on failure."""
    try:
        return jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            issuer=settings.jwt_issuer,
        )
    except jwt.ExpiredSignatureError as exc:
        raise socketio.exceptions.ConnectionRefusedError("token_expired") from exc
    except jwt.PyJWTError as exc:
        raise socketio.exceptions.ConnectionRefusedError("invalid_token") from exc


async def _user_is_in_room(user_id: int, room_id: int) -> bool:
    async with async_session_factory() as session:
        rp = await session.get(RoomParticipant, (room_id, user_id))
        return rp is not None


async def _user_room_ids(user_id: int) -> list[int]:
    """Return every room the user is a participant of.

    Used at connection time so the socket gets auto-subscribed to all the
    user's rooms — that way ``message_new`` events for any of them update
    the sidebar (unread badges + last-message preview) regardless of which
    chat is currently open in the UI.
    """
    async with async_session_factory() as session:
        stmt = select(RoomParticipant.room_id).where(RoomParticipant.user_id == user_id)
        result = await session.execute(stmt)
        return [int(r) for r in result.scalars().all()]


@sio.event
async def connect(sid: str, environ: dict[str, Any], auth: dict[str, Any] | None = None):
    """Validate JWT and remember user identity in the socket session."""
    token = _extract_token(auth, environ)
    if not token:
        log.warning("socket_connect_rejected", sid=sid, reason="missing_token")
        raise socketio.exceptions.ConnectionRefusedError("missing_token")

    payload = _decode_jwt(token)
    user_id = payload.get("user_id")
    if not user_id:
        log.warning("socket_connect_rejected", sid=sid, reason="no_user_id_claim")
        raise socketio.exceptions.ConnectionRefusedError("no_user_id_claim")

    await sio.save_session(
        sid,
        {
            "user_id": int(user_id),
            "username": payload.get("username") or "",
            "is_admin": bool(payload.get("is_admin")),
        },
    )

    # Auto-subscribe the socket to every room the user belongs to. Without
    # this, ``message_new`` events only flow into the chat that's actively
    # open in the UI (because that's the only one ``join_room`` was called
    # for) — sidebar previews and unread badges stay stale until a manual
    # refetch.
    try:
        room_ids = await _user_room_ids(int(user_id))
        for rid in room_ids:
            await sio.enter_room(sid, f"room:{rid}")
        # Per-user channel for events that aren't tied to a specific room
        # (e.g., a brand-new chat being created). The frontend can listen
        # on it without first knowing the room id.
        await sio.enter_room(sid, f"user:{int(user_id)}")
        log.info(
            "socket_auto_joined", sid=sid, user_id=user_id, rooms=len(room_ids)
        )
    except Exception:  # noqa: BLE001 — never block connect on a join hiccup
        log.exception("socket_auto_join_failed", sid=sid, user_id=user_id)

    log.info("socket_connected", sid=sid, user_id=user_id)


@sio.event
async def disconnect(sid: str):
    try:
        session = await sio.get_session(sid)
    except KeyError:
        session = {}
    log.info("socket_disconnected", sid=sid, user_id=session.get("user_id"))


@sio.event
async def join_room(sid: str, data: dict[str, Any]):
    """Subscribe the socket to a chat room — only if user is a participant."""
    session = await sio.get_session(sid)
    user_id = session["user_id"]
    room_id = data.get("room_id") if isinstance(data, dict) else None
    if room_id is None:
        return {"ok": False, "error": "missing_room_id"}

    try:
        room_id_int = int(room_id)
    except (TypeError, ValueError):
        return {"ok": False, "error": "invalid_room_id"}

    if not await _user_is_in_room(user_id, room_id_int):
        log.warning("join_room_denied", user_id=user_id, room_id=room_id_int)
        return {"ok": False, "error": "not_a_member"}

    await sio.enter_room(sid, f"room:{room_id_int}")
    log.info("join_room", user_id=user_id, room_id=room_id_int)
    return {"ok": True}


@sio.event
async def leave_room(sid: str, data: dict[str, Any]):
    room_id = data.get("room_id") if isinstance(data, dict) else None
    if room_id is None:
        return {"ok": False, "error": "missing_room_id"}
    try:
        await sio.leave_room(sid, f"room:{int(room_id)}")
    except (TypeError, ValueError):
        return {"ok": False, "error": "invalid_room_id"}
    return {"ok": True}


@sio.event
async def typing(sid: str, data: dict[str, Any]):
    """Forward a typing indicator to other participants of the same room."""
    session = await sio.get_session(sid)
    user_id = session["user_id"]
    room_id = data.get("room_id") if isinstance(data, dict) else None
    if room_id is None:
        return
    is_typing = bool(data.get("is_typing", True)) if isinstance(data, dict) else True
    await sio.emit(
        "user_typing",
        {"room_id": int(room_id), "user_id": user_id, "is_typing": is_typing},
        room=f"room:{int(room_id)}",
        skip_sid=sid,
    )


@sio.event
async def mark_read(sid: str, data: dict[str, Any]):
    """WS-side mark-read: persists `last_read_message_id` and broadcasts.

    Mirrors POST /api/messenger/v1/messages/room/{room_id}/read/{message_id}.
    """
    session = await sio.get_session(sid)
    user_id = session["user_id"]
    if not isinstance(data, dict):
        return
    room_id = data.get("room_id")
    message_id = data.get("message_id")
    if room_id is None or not message_id:
        return

    async with async_session_factory() as db:
        rp = await db.get(RoomParticipant, (int(room_id), user_id))
        if not rp:
            return
        rp.last_read_message_id = message_id
        await db.commit()

    await sio.emit(
        "message_read",
        {"room_id": int(room_id), "message_id": str(message_id), "reader_user_id": user_id},
        room=f"room:{int(room_id)}",
        skip_sid=sid,
    )
