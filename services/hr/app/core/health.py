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
    """Readiness probe — are dependencies available?"""
    # TODO: Add actual database connectivity check
    db_status = "pending"  # Replace with asyncpg.connect() check

    return ReadyResponse(
        status="ok",
        service=settings.service_name,
        database=db_status,
    )
