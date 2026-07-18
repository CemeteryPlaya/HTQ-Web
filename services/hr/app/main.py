"""
HR Service — FastAPI microservice for HTQWeb platform.

Handles: employees, departments, positions, vacancies, applications,
         time tracking, documents, audit log.
Part of the Strangler Fig migration pattern (Phase 1b).
"""

import asyncio
import logging
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.admin import create_admin
from app.core.settings import settings
from htqweb_metrics import setup_metrics
from app.db import async_session_factory, engine
from app.middleware.request_id import RequestIDMiddleware
from app.services.demo_seed_service import seed_demo_data
from app.workers import actors as _actors  # noqa: F401  init broker for enqueue
from app.workers.user_identity_sync import run_user_identity_sync_loop
from app.api.health import router as health_router
from app.api.v1.employees import router as employees_router
from app.api.v1.departments import router as departments_router
from app.api.v1.positions import router as positions_router
from app.api.v1.vacancies import router as vacancies_router
from app.api.v1.applications import router as applications_router
from app.api.v1.time import router as time_router
from app.api.v1.documents import router as documents_router
from app.api.v1.audit import router as audit_router
from app.api.v1.personnel_history import router as personnel_history_router
from app.api.v1.org import router as org_router
from app.api.v1.pmo import router as pmo_router
from app.api.v1.department_files import router as department_files_router
from app.api.v1.share_links import router as share_links_router
from app.api.v1.internal import router as internal_router
from app.api.v1.mongo_documents import router as mongo_documents_router
from app.api.v1.employee_card import router as employee_card_router
from app.api.v1.calendar import router as calendar_router, employee_calendar_router
from app.api.v1.staffing import router as staffing_router
from app.api.public.org import router as public_org_router, limiter  # limiter attached to app below
from app.api.public.employee import router as public_employee_router
from app.mongo import ensure_indexes as mongo_ensure_indexes, close_mongo

API_PREFIX = settings.api_prefix  # /api/hr/v1


async def _maybe_seed_demo() -> None:
    """Idempotent demo-data seeder, gated by ``settings.auto_seed_demo``.

    Runs once on lifespan startup. Skipped entirely in production. Safe to
    call repeatedly: the seed function itself returns ``status='skipped'``
    when demo rows are already present.
    """
    if settings.service_env == "production":
        return
    if not settings.auto_seed_demo:
        return
    try:
        async with async_session_factory() as session:
            try:
                result = await seed_demo_data(session)
                await session.commit()
                logging.info("hr_demo_seed", extra={"result": result})
            except Exception:
                await session.rollback()
                raise
    except Exception as exc:  # pragma: no cover — startup must not crash on seed errors
        logging.exception("hr_demo_seed_failed: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.info("service_startup", extra={"service": settings.service_name, "port": settings.service_port})
    await _maybe_seed_demo()
    await mongo_ensure_indexes()
    # Background subscriber that mirrors user identity (name/email/phone/avatar)
    # into the linked Employee row so the HR card and org chart stay in sync
    # with the user-service's canonical identity data.
    sync_task = asyncio.create_task(run_user_identity_sync_loop())
    try:
        yield
    finally:
        sync_task.cancel()
        try:
            await sync_task
        except asyncio.CancelledError:
            pass
        await close_mongo()
        logging.info("service_shutdown", extra={"service": settings.service_name})


def get_application() -> FastAPI:
    """Create and configure the FastAPI application."""

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
        title="HR Service",
        version="1.0.0",
        description="HR management microservice for HTQWeb enterprise platform",
        lifespan=lifespan,
        docs_url="/docs" if settings.service_env != "production" else None,
        redoc_url="/redoc" if settings.service_env != "production" else None,
        openapi_url="/openapi.json" if settings.service_env != "production" else None,
    )

    setup_metrics(app, service_name=settings.service_name)

    # Middleware
    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(SlowAPIMiddleware)

    # Rate limiter state (required by slowapi)
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    # OpenTelemetry
    FastAPIInstrumentor.instrument_app(app)

    # Health (no prefix — required by Docker healthcheck and gateway)
    app.include_router(health_router)

    # API v1 routes
    app.include_router(employees_router, prefix=API_PREFIX)
    app.include_router(employee_calendar_router, prefix=API_PREFIX)
    app.include_router(employee_card_router, prefix=API_PREFIX)
    app.include_router(departments_router, prefix=API_PREFIX)
    app.include_router(positions_router, prefix=API_PREFIX)
    app.include_router(vacancies_router, prefix=API_PREFIX)
    app.include_router(applications_router, prefix=API_PREFIX)
    app.include_router(time_router, prefix=API_PREFIX)
    app.include_router(documents_router, prefix=API_PREFIX)
    app.include_router(audit_router, prefix=API_PREFIX)
    app.include_router(personnel_history_router, prefix=API_PREFIX)
    app.include_router(org_router, prefix=API_PREFIX)
    app.include_router(pmo_router, prefix=API_PREFIX)
    app.include_router(department_files_router, prefix=API_PREFIX)
    app.include_router(share_links_router, prefix=API_PREFIX)
    app.include_router(internal_router, prefix=f"{API_PREFIX}/internal")
    app.include_router(mongo_documents_router, prefix=API_PREFIX)
    app.include_router(calendar_router, prefix=API_PREFIX)
    app.include_router(staffing_router, prefix=API_PREFIX)

    # Public routes (no auth, rate-limited)
    app.include_router(public_org_router, prefix=API_PREFIX)
    app.include_router(public_employee_router, prefix=API_PREFIX)

    # Admin (sqladmin) — mounted at /admin/, JWT cookie auth
    create_admin(app, engine)

    return app


app = get_application()
