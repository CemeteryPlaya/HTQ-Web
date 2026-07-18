"""
CMS Service — FastAPI microservice for HTQWeb platform.

This service handles content management: news articles, contact request forms,
and conference runtime configuration. Each service owns its data, its admin
(sqladmin), and its background workers (Dramatiq + APScheduler).
"""

import logging
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.core.settings import settings
from htqweb_metrics import setup_metrics
from app.core.health import router as health_router
from app.middleware.request_id import RequestIDMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown hooks."""
    logging.info("service_startup", extra={"service": settings.service_name, "port": settings.service_port})

    # Start the APScheduler for scheduled publishing
    from app.workers.scheduler import start_scheduler, stop_scheduler
    start_scheduler()

    yield

    stop_scheduler()
    logging.info("service_shutdown", extra={"service": settings.service_name})


class _HealthAccessFilter(logging.Filter):
    """Drop uvicorn access lines for the docker healthcheck endpoint.

    Docker pings /health/ every 10s; without filtering, the access log
    becomes 99% healthcheck noise that drowns real traffic.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        return "/health/" not in record.getMessage()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""

    logging.getLogger("uvicorn.access").addFilter(_HealthAccessFilter())

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    app = FastAPI(
        title="CMS Service",
        version="0.1.0",
        description="Content management for HTQWeb: news, contact requests, conference config",
        lifespan=lifespan,
        docs_url="/docs" if settings.service_env != "production" else None,
        redoc_url="/redoc" if settings.service_env != "production" else None,
        openapi_url="/openapi.json" if settings.service_env != "production" else None,
    )

    setup_metrics(app, service_name=settings.service_name)

    app.add_middleware(RequestIDMiddleware)

    # Rate-limit error handler for slowapi
    app.state.limiter = __import__("app.api.v1.contact_requests", fromlist=["limiter"]).limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    # Health (no prefix — gateway and Docker healthcheck hit /health/)
    app.include_router(health_router)

    # API v1 routers
    from app.api.v1 import news as news_router
    from app.api.v1 import contact_requests as contact_requests_router
    from app.api.v1 import conference as conference_router
    from app.api.v1 import taxonomy as taxonomy_router

    app.include_router(news_router.router, prefix="/api/cms/v1/news")
    app.include_router(contact_requests_router.router, prefix="/api/cms/v1/contact-requests")
    app.include_router(conference_router.router, prefix="/api/cms/v1/conference")
    app.include_router(taxonomy_router.categories_router, prefix="/api/cms/v1/categories")
    app.include_router(taxonomy_router.tags_router, prefix="/api/cms/v1/tags")

    # Admin (sqladmin) — wires JWT auth backend and ModelView registrations
    from app.admin import create_admin
    from app.db import engine
    create_admin(app, engine)

    # Import actors so broker is initialized for enqueue from web process
    from app.workers import actors as _actors  # noqa: F401

    return app


app = create_app()
