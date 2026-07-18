"""
Media Service — FastAPI microservice for HTQWeb platform.

This service handles file uploads, secure downloads (with Range support),
and metadata tracking. Supports LocalStorage and S3Storage.
"""


from contextlib import asynccontextmanager


from fastapi import FastAPI

from app.core.settings import settings
from app.core.metrics import setup_metrics
from app.core.health import router as health_router
from app.middleware.request_id import RequestIDMiddleware
from app.core.logging import configure_logging, get_logger
from app.middleware.request_logging import RequestLoggingMiddleware

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown hooks."""
    log.info("service_startup", extra={"service": settings.service_name, "port": settings.service_port})
    yield
    log.info("service_shutdown", extra={"service": settings.service_name})


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    configure_logging()

    app = FastAPI(
        title="Media Service",
        version="0.1.0",
        description="Media and file storage for HTQWeb",
        lifespan=lifespan,
        docs_url="/docs" if settings.service_env != "production" else None,
        redoc_url="/redoc" if settings.service_env != "production" else None,
        openapi_url="/openapi.json" if settings.service_env != "production" else None,
    )

    setup_metrics(app, service_name=settings.service_name)

    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(RequestIDMiddleware)

    # Health (no prefix — gateway and Docker healthcheck hit /health/)
    app.include_router(health_router)

    # API v1 routers
    from app.api.v1 import files as files_router

    app.include_router(files_router.router, prefix="/api/media/v1/files")

    # Admin (sqladmin) — wires JWT auth backend and ModelView registrations
    from app.admin import create_admin
    from app.db import engine
    create_admin(app, engine)

    # Import actors so broker is initialized for enqueue from web process
    from app.workers import actors as _actors  # noqa: F401

    return app


app = create_app()
