"""
Messenger Service — FastAPI microservice for HTQWeb platform.

Handles chat, rooms, E2EE keys, and real-time Socket.IO communication.
"""


import asyncio
from contextlib import asynccontextmanager


from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from app.core.settings import settings
from htqweb_metrics import setup_metrics
from app.core.logging import configure_logging, get_logger
from app.api.socket import sio_app
from app.services.system_bots import ensure_system_bots
from app.workers.bot_dispatch import run_bot_dispatch_loop
from app.workers.replica_sync import run_user_replica_sync_loop

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown hooks."""
    log.info("service_startup", extra={"service": settings.service_name, "port": settings.service_port})
    # Subscribe to user-service pub/sub so ChatUserReplica stays in sync.
    replica_task = asyncio.create_task(run_user_replica_sync_loop())
    # Insert the 5 system bot rows (idempotent) before the dispatcher
    # subscribes — otherwise the first notify event could race the bots
    # and fail to open a DM.
    try:
        await ensure_system_bots()
    except Exception as exc:  # noqa: BLE001
        log.warning("system_bots_bootstrap_failed", extra={"err": str(exc)})
    # Dispatch notify.* Redis events into bot DM messages.
    bot_task = asyncio.create_task(run_bot_dispatch_loop())
    try:
        yield
    finally:
        for task in (replica_task, bot_task):
            task.cancel()
        for task in (replica_task, bot_task):
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        log.info("service_shutdown", extra={"service": settings.service_name})


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    configure_logging()

    app = FastAPI(
        title="Messenger Service",
        version="0.1.0",
        description="Real-time chat and messaging for HTQWeb",
        lifespan=lifespan,
        docs_url="/docs" if settings.service_env != "production" else None,
        redoc_url="/redoc" if settings.service_env != "production" else None,
        openapi_url="/openapi.json" if settings.service_env != "production" else None,
    )

    setup_metrics(app, service_name=settings.service_name)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Health (no prefix — gateway and Docker healthcheck hit /health/)
    @app.get("/health/", include_in_schema=False)
    async def health_check():
        return {"status": "ok", "service": "messenger"}

    # API v1 routers
    from app.api.v1 import rooms as rooms_router
    from app.api.v1 import messages as messages_router
    from app.api.v1 import keys as keys_router
    from app.api.v1 import users as users_router
    from app.api.v1 import read as read_router
    from app.api.v1 import attachments as attachments_router
    from app.api.v1 import admin as admin_router
    from app.api.v1 import internal as internal_router

    app.include_router(rooms_router.router, prefix="/api/messenger/v1/rooms")
    app.include_router(messages_router.router, prefix="/api/messenger/v1/messages")
    app.include_router(keys_router.router, prefix="/api/messenger/v1/keys")
    app.include_router(users_router.router, prefix="/api/messenger/v1/users")
    app.include_router(read_router.router, prefix="/api/messenger/v1")
    app.include_router(attachments_router.router, prefix="/api/messenger/v1/attachments")
    app.include_router(admin_router.router, prefix="/api/messenger/v1/admin")
    app.include_router(internal_router.router, prefix="/api/messenger/v1/internal")

    # Attachments live in S3 (htqweb-messenger bucket). The browser hits
    # ``/api/messenger/v1/attachments/file/{id}?sig=...&exp=...`` and gets
    # a 302 to a fresh presigned S3 URL. No StaticFiles mount needed.

    # Admin (sqladmin)
    from app.admin import create_admin
    from app.db import engine
    create_admin(app, engine)

    # Socket.IO is mounted last (after all REST routes) so the root `/` mount
    # acts as a fallthrough for engineio traffic only. socketio_path already
    # contains the full `/ws/messenger/socket.io` prefix because Starlette's
    # Mount sets `root_path` but doesn't rewrite `scope["path"]`, while
    # engineio's ASGIApp matches against the raw `scope["path"]`.
    app.mount("/", sio_app)

    return app


app = create_app()
