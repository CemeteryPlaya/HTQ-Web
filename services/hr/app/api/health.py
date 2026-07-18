"""Health check endpoints."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db_session

router = APIRouter(tags=["health"])


@router.get("/health/")
async def health_check():
    return {
        "status": "ok",
        "service": "hr-service",
        "version": "1.0.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/health/ready")
async def readiness_check(db: AsyncSession = Depends(get_db_session)):
    try:
        await db.execute(text("SELECT 1"))
        return {"status": "ready", "service": "hr-service"}
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"status": "not_ready", "reason": str(exc)},
        )
