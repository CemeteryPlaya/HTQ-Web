"""FastAPI application entry point."""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.admin import create_admin
from app.api import v1_router
from app.core.settings import settings
from htqweb_metrics import setup_metrics
from app.db import engine
from app.core.health import router as health_router
from app.middleware import RequestIDMiddleware
from app.workers import actors as _actors  # noqa: F401  ensures broker is configured
from app.workers.notify_sync import run_notify_sync_loop
from app.workers.replica_sync import run_user_replica_sync_loop

# Configure structured logging
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    logger.info("Task service starting up...")
    # Subscribe to user-service pub/sub so the local users replica stays current.
    replica_task = asyncio.create_task(run_user_replica_sync_loop())
    # Subscribe to messenger/email notify events so they turn into Notification
    # rows visible in the bell dropdown + /notifications page + toast popups.
    notify_task = asyncio.create_task(run_notify_sync_loop())
    try:
        yield
    finally:
        for task in (replica_task, notify_task):
            task.cancel()
        for task in (replica_task, notify_task):
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        logger.info("Task service shutting down...")


def create_app() -> FastAPI:
    """Create and configure FastAPI application."""
    app = FastAPI(
        title="Task Service",
        description="Task tracking and project management microservice",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    setup_metrics(app, service_name=settings.service_name)

    app.add_middleware(RequestIDMiddleware)

    app.include_router(health_router)
    app.include_router(v1_router)

    create_admin(app, engine)

    return app


app = create_app()
