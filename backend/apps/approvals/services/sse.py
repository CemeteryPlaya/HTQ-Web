"""Server-Sent Events plumbing for ``/api/requests/v1/stream``.

Ported from ``services/requests/app/api/v1/stream.py``. This module holds
everything that is NOT Django-specific so it can be tested without a socket:
the wire formatting is a pure function, and the event source is injected.

Why SSE and not polling: an approver needs to see "your step is ready" while
sitting on the page, and the dispatch path already publishes to Redis for
this exact purpose (``dispatch.publish_sse``).

**The token travels in the query string.** ``EventSource`` cannot set request
headers, so the browser has no way to send ``Authorization`` — the original
accepted ``?token=`` for that reason and PLAN.md §6.2 pins the behaviour.
This is a real exposure (query strings land in access logs, proxy logs and
``Referer``), mitigated only by the tokens being short-lived. The header form
is still accepted and preferred for non-browser clients. Do not "clean this
up" by dropping the query form without replacing the browser transport.
"""

from __future__ import annotations

import asyncio
import json
import logging

from django.conf import settings

from htqweb.authn.jwt import AuthError, decode_token

logger = logging.getLogger(__name__)

# Comment frames keep proxies from reaping an idle connection. 25s sits below
# the common 30s idle timeouts (nginx's proxy_read_timeout default is 60s,
# but load balancers in front are often tighter).
HEARTBEAT_SECONDS = 25.0


class StreamAuthError(Exception):
    """Bad or missing credentials — the view turns this into a 401."""


def authenticate(*, query_token: str | None,
                 authorization: str | None) -> int:
    """Resolve the streaming user's id, or raise ``StreamAuthError``.

    Accepts the query parameter first (that is the browser's only option),
    falling back to a normal bearer header.
    """
    raw = query_token
    if not raw:
        header = authorization or ""
        if header.lower().startswith("bearer "):
            raw = header.split(None, 1)[1].strip()
    if not raw:
        raise StreamAuthError("missing token")

    try:
        payload = decode_token(raw)
    except AuthError as exc:
        raise StreamAuthError(f"invalid token: {exc}") from exc
    except Exception as exc:  # malformed claims -> pydantic ValidationError
        raise StreamAuthError(f"invalid token: {exc}") from exc

    if payload.token_type != "access":
        # A 7-day refresh token must not open a long-lived stream.
        raise StreamAuthError("invalid token: not an access token")
    if not isinstance(payload.user_id, int):
        raise StreamAuthError("token missing user_id")
    return payload.user_id


def format_event(raw_data: str) -> str | None:
    """Render one published payload as an SSE frame.

    Returns ``None`` for anything unparseable, so a stray publish cannot
    break the stream for a connected client.

    The event name is sanitised: SSE field values are newline-delimited, so a
    name containing a newline would let a publisher forge extra frames — and
    a colon would corrupt the field. Both are replaced rather than rejected,
    matching the original.
    """
    try:
        parsed = json.loads(raw_data)
    except (ValueError, TypeError):
        return None
    if not isinstance(parsed, dict):
        return None
    name = str(parsed.get("event", "message")).replace("\n", " ").replace(":", "_")
    # ``data`` carries the original JSON verbatim so the client parses one
    # object rather than a re-serialised copy.
    return f"event: {name}\ndata: {raw_data}\n\n"


def heartbeat() -> str:
    """A comment frame — ignored by ``EventSource``, keeps the socket warm."""
    return ": heartbeat\n\n"


def opening_frame() -> str:
    """Some clients hold the response until the first byte arrives."""
    return ": connected\n\n"


async def default_subscriber(channel: str):
    """Async generator of raw payload strings from Redis pub/sub.

    Separated from ``event_stream`` so tests can inject a list instead of
    standing up Redis.
    """
    import redis.asyncio as aioredis

    client = aioredis.Redis.from_url(
        getattr(settings, "REDIS_URL", "redis://localhost:6379/0"))
    pubsub = client.pubsub()
    await pubsub.subscribe(channel)
    try:
        while True:
            try:
                message = await asyncio.wait_for(
                    pubsub.get_message(ignore_subscribe_messages=True,
                                       timeout=None),
                    timeout=HEARTBEAT_SECONDS,
                )
            except asyncio.TimeoutError:
                yield None          # nothing to send — caller emits a heartbeat
                continue
            if message is None or message.get("type") != "message":
                continue
            data = message.get("data") or b""
            if isinstance(data, bytes):
                data = data.decode("utf-8", errors="replace")
            yield data
    finally:
        try:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()
            await client.aclose()
        except Exception:  # noqa: BLE001 - teardown must never mask the exit
            logger.debug("sse teardown failed for %s", channel, exc_info=True)


async def event_stream(channel: str, *, subscriber=None):
    """The response body: an opening comment, then frames until disconnect.

    ``subscriber`` yields raw payload strings, or ``None`` to mean "idle,
    send a heartbeat". Injected so the tests drive it directly.
    """
    yield opening_frame()
    source = (subscriber or default_subscriber)(channel)
    try:
        async for raw in source:
            if raw is None:
                yield heartbeat()
                continue
            frame = format_event(raw)
            if frame is not None:
                yield frame
    except asyncio.CancelledError:
        # Client went away — propagate so the server can close cleanly.
        raise
    except Exception:
        # One broken stream must not take the process with it.
        logger.warning("sse stream failed for %s", channel, exc_info=True)
    finally:
        aclose = getattr(source, "aclose", None)
        if aclose is not None:
            await aclose()
