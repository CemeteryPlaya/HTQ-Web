"""Async S2S client for hr-service internal endpoints."""

import httpx

from app.core.settings import settings


class HrS2SError(Exception):
    pass


async def fetch_supervisor_user_id(user_id: int) -> int | None:
    """Return the user_id of ``user_id``'s supervisor (= head of their department).

    Returns None if hr knows nothing about this user or they have no supervisor.
    Raises ``HrS2SError`` only on 5xx/network failure so the runtime can decide
    whether to fail the request or retry."""
    url = settings.hr_internal_url.rstrip("/") + "/api/hr/v1/internal/supervisor"
    headers = {"X-Internal-Token": settings.internal_s2s_token}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url, params={"user_id": user_id}, headers=headers)
    except httpx.HTTPError as exc:
        raise HrS2SError(f"hr-service unreachable: {exc}") from exc
    if resp.status_code >= 500:
        raise HrS2SError(f"hr-service returned {resp.status_code}: {resp.text[:200]}")
    if resp.status_code >= 400:
        # 4xx (auth, bad params) → treat as "no supervisor"; don't pretend hr is down.
        return None
    return resp.json().get("supervisor_user_id")
