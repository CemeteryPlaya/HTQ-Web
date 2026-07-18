"""
__service_name__ Service — FastAPI microservice for HTQWeb platform.

This service handles __service_description__.
Each service owns its data, its admin (sqladmin), and its background workers (Dramatiq).
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.logging import configure_logging, get_logger
from app.core.settings import settings
from app.core.health import router as health_router
from app.middleware.request_id import RequestIDMiddleware
from app.middleware.request_logging import RequestLoggingMiddleware


log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown hooks."""
    log.info("service_startup", port=settings.service_port, env=settings.service_env)
    yield
    log.info("service_shutdown")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    configure_logging()

    app = FastAPI(
        title=settings.service_name,
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if settings.service_env != "production" else None,
        redoc_url="/redoc" if settings.service_env != "production" else None,
        openapi_url="/openapi.json" if settings.service_env != "production" else None,
    )

    # Outermost first — RequestID binds contextvars; RequestLogging emits events.
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(RequestIDMiddleware)

    # Health (no prefix — gateway and Docker healthcheck hit /health/)
    app.include_router(health_router)

    # API v1 — register routers from app.api.v1.*
    # from app.api.v1 import example
    # app.include_router(example.router, prefix="/api/__service_name__/v1")

    # Admin (sqladmin) — wires JWT auth backend and ModelView registrations
    # from app.admin import create_admin
    # from app.db import engine
    # create_admin(app, engine)

    # Dramatiq broker init — importing workers.actors sets the RedisBroker.
    # from app.workers import actors as _actors  # noqa: F401

    return app


app = create_app()
