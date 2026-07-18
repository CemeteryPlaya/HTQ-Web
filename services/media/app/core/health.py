"""Health check router — /health/."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()


@router.get("/health/", include_in_schema=False)
async def health_check() -> JSONResponse:
    return JSONResponse({"status": "ok", "service": "media"})
