"""Health check and readiness utilities."""

from datetime import datetime, timezone

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.settings import settings


class HealthResponse(BaseModel):
    status: str
    service: str
    timestamp: str


class ReadyResponse(BaseModel):
    status: str
    service: str
    database: str = "unknown"


router = APIRouter()


@router.get("/health/", response_model=HealthResponse)
async def health_check():
    """Basic liveness probe — is the process running?"""
    return HealthResponse(
        status="ok",
        service=settings.service_name,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@router.get("/health/ready/", response_model=ReadyResponse)
async def readiness_check():
    """Readiness probe — verify the database is reachable."""
    from sqlalchemy import text
    from app.db import engine

    db_status = "ok"
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        db_status = "error"

    return ReadyResponse(
        status="ok" if db_status == "ok" else "degraded",
        service=settings.service_name,
        database=db_status,
    )
