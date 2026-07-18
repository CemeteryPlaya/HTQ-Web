from typing import Any
from fastapi import HTTPException
from app.core.settings import settings

async def get_google_auth_url(state: str) -> str:
    if not settings.google_client_id:
        raise HTTPException(503, "OAuth not configured")
    # Stub for URL generation
    return f"https://accounts.google.com/o/oauth2/v2/auth?client_id={settings.google_client_id}&state={state}"

async def exchange_google_code(code: str) -> dict[str, Any]:
    if not settings.google_client_id:
        raise HTTPException(503, "OAuth not configured")
    return {"access_token": "stub", "refresh_token": "stub", "expires_in": 3600}

async def refresh_google_token(refresh_token: str) -> dict:
    if not settings.google_client_id:
        raise HTTPException(503, "OAuth not configured")
    return {"access_token": "stub_refreshed", "expires_in": 3600}

async def get_google_user_email(access_token: str) -> str:
    if not settings.google_client_id:
        raise HTTPException(503, "OAuth not configured")
    return "test@gmail.com"

# Analogous stubs for microsoft_* if needed
