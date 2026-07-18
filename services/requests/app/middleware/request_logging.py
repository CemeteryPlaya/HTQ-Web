"""HTTP request/response logging — one structured event per request."""

import time

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import get_logger


log = get_logger(__name__)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        started = time.perf_counter()
        method = request.method
        path = request.url.path

        log.info(
            "request_received",
            method=method,
            path=path,
            client=request.client.host if request.client else None,
        )

        try:
            response = await call_next(request)
        except Exception as exc:
            duration_ms = (time.perf_counter() - started) * 1000
            log.error(
                "request_failed",
                method=method,
                path=path,
                duration_ms=round(duration_ms, 2),
                error=repr(exc),
            )
            raise

        duration_ms = (time.perf_counter() - started) * 1000
        log.info(
            "request_completed",
            method=method,
            path=path,
            status=response.status_code,
            duration_ms=round(duration_ms, 2),
        )
        return response
