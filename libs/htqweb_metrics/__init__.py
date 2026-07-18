"""Prometheus HTTP metrics for HTQWeb FastAPI services.

Zero extra dependencies: ``prometheus_client`` already ships with every
service via dramatiq. Usage (once, right after ``FastAPI()``)::

    from htqweb_metrics import setup_metrics
    setup_metrics(app, service_name="task-service")

Exposes ``GET /metrics`` (excluded from the OpenAPI schema) and records:

- ``http_requests_total{service, method, handler, status}``
- ``http_request_duration_seconds{service, method, handler}`` (histogram)
- ``http_requests_in_flight{service}``

``handler`` is the *route template* (``/api/tasks/v1/tasks/{task_id}/``),
never the raw path — raw paths would explode label cardinality.

media-service builds from its own Docker context without ``libs/`` and keeps
a verbatim copy at ``services/media/app/core/metrics.py`` — update both.
"""

from __future__ import annotations

import time

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Match

# Module-level singletons: uvicorn runs one process per container, and the
# default REGISTRY already carries python_/process_ collectors for free.
_REQUESTS = Counter(
    "http_requests_total",
    "HTTP requests processed.",
    ["service", "method", "handler", "status"],
)
_DURATION = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration.",
    ["service", "method", "handler"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)
_IN_FLIGHT = Gauge(
    "http_requests_in_flight",
    "HTTP requests currently being served.",
    ["service"],
)


def _route_template(request: Request) -> str:
    """Resolve the matched route template without touching handler internals."""
    app_routes = request.app.routes
    for route in app_routes:
        match, _ = route.matches(request.scope)
        if match == Match.FULL:
            return getattr(route, "path", request.url.path)
    return "unmatched"


def setup_metrics(app, service_name: str) -> None:
    """Attach the metrics middleware and the /metrics endpoint to *app*."""

    @app.middleware("http")
    async def _prometheus_middleware(request: Request, call_next):
        if request.url.path == "/metrics":
            return await call_next(request)
        _IN_FLIGHT.labels(service_name).inc()
        started = time.perf_counter()
        status = "500"  # if call_next raises, count it as a 500
        try:
            response = await call_next(request)
            status = str(response.status_code)
            return response
        finally:
            elapsed = time.perf_counter() - started
            handler = _route_template(request)
            _REQUESTS.labels(service_name, request.method, handler, status).inc()
            _DURATION.labels(service_name, request.method, handler).observe(elapsed)
            _IN_FLIGHT.labels(service_name).dec()

    @app.get("/metrics", include_in_schema=False)
    async def _metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
