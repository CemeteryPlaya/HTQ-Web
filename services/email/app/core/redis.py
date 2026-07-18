"""Async Redis client for short-lived state (PKCE nonces, etc.).

The same Redis instance powers Dramatiq queues at a different DB index
(see REDIS_URL). Service-side state lives here. Created lazily and
reused across requests.
"""

from __future__ import annotations

import redis.asyncio as aioredis

from app.core.settings import settings


_client: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    """Return a process-wide async Redis client. Created on first use."""
    global _client
    if _client is None:
        _client = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _client


async def close_redis() -> None:
    """Close the shared client. Called from FastAPI lifespan shutdown."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
