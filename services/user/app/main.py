"""
User/Identity Service — FastAPI microservice for HTQWeb platform.

Owns: identity, auth (JWT issuance), profile, registration, admin user mgmt,
personal items (notes). Issues the JWT cookie used by every other service's
sqladmin AuthenticationBackend.
"""

import logging
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

from app.admin import create_admin
from app.api.v1 import admin as admin_router
from app.api.v1 import auth as auth_router
from app.api.v1 import client_errors as client_errors_router
from app.api.v1 import items as items_router
from app.api.v1 import profile as profile_router
from app.api.v1 import registration as registration_router
from app.api.v1 import users as users_router
from app.core.health import router as health_router
from app.core.settings import settings
from htqweb_metrics import setup_metrics
from app.db import engine
from app.middleware.request_id import RequestIDMiddleware
from app.workers import actors as _actors  # noqa: F401  init broker for enqueue


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.info(
        "service_startup",
        extra={"service": settings.service_name, "port": settings.service_port},
    )
    yield
    logging.info("service_shutdown", extra={"service": settings.service_name})


def get_application() -> FastAPI:
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
        title="User/Identity Service",
        version="0.2.0",
        description="JWT authority and user management for HTQWeb platform",
        lifespan=lifespan,
        docs_url="/docs" if settings.service_env != "production" else None,
        redoc_url="/redoc" if settings.service_env != "production" else None,
        openapi_url="/openapi.json" if settings.service_env != "production" else None,
    )

    setup_metrics(app, service_name=settings.service_name)

    app.add_middleware(RequestIDMiddleware)

    FastAPIInstrumentor.instrument_app(app)

    app.include_router(health_router)
    app.include_router(auth_router.router)
    app.include_router(auth_router.admin_router)
    app.include_router(registration_router.router)
    app.include_router(profile_router.router)
    app.include_router(users_router.router)
    app.include_router(admin_router.router)
    app.include_router(items_router.router)
    app.include_router(client_errors_router.router)

    create_admin(app, engine)

    return app


app = get_application()
