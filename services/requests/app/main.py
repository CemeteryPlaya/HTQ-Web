"""
requests Service — FastAPI microservice for HTQWeb platform.

This service handles Approval requests (Lark-style) microservice.
Each service owns its data, its admin (sqladmin), and its background workers (Dramatiq).
"""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.logging import configure_logging, get_logger
from app.core.settings import settings
from htqweb_metrics import setup_metrics
from app.core.health import router as health_router
from app.middleware.request_id import RequestIDMiddleware
from app.middleware.request_logging import RequestLoggingMiddleware
from app.api.v1 import router as v1_router
from app.workers import actors as _actors  # noqa: F401  — configures the broker
from app.workers.replica_sync import run_replica_sync_loop


log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown hooks."""
    log.info("service_startup", port=settings.service_port, env=settings.service_env)
    replica_task = asyncio.create_task(run_replica_sync_loop())
    # Kick off the self-rescheduling nightly stats reconciliation. The actor
    # re-queues itself for the next 03:00 UTC, so we only need to bootstrap
    # once per process start. Best-effort — if Redis is down at boot the next
    # restart will pick up.
    try:
        from app.workers.notifications import rollup_stats_daily, _next_03_local_ms
        rollup_stats_daily.send_with_options(delay=_next_03_local_ms())
    except Exception as exc:  # noqa: BLE001
        log.warning("stats_rollup_bootstrap_failed", err=str(exc))
    try:
        yield
    finally:
        replica_task.cancel()
        try:
            await replica_task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass
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

    setup_metrics(app, service_name=settings.service_name)

    # Outermost first — RequestID binds contextvars; RequestLogging emits events.
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(RequestIDMiddleware)

    # Health (no prefix — gateway and Docker healthcheck hit /health/)
    app.include_router(health_router)
    app.include_router(v1_router)

    return app


app = create_app()
