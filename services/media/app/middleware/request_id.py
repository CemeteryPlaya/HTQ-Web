"""Request ID + correlation ID middleware.

- X-Request-ID is per-hop (propagated to response).
- X-Correlation-ID is end-to-end across services; bound to structlog contextvars
  so every log line in the request carries it.
"""

import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response


REQUEST_ID_HEADER = "x-request-id"
CORRELATION_ID_HEADER = "x-correlation-id"


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid.uuid4())
        correlation_id = request.headers.get(CORRELATION_ID_HEADER) or request_id

        request.state.request_id = request_id
        request.state.correlation_id = correlation_id

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            correlation_id=correlation_id,
        )

        try:
            response = await call_next(request)
        finally:
            structlog.contextvars.clear_contextvars()

        response.headers[REQUEST_ID_HEADER] = request_id
        response.headers[CORRELATION_ID_HEADER] = correlation_id
        response.headers["X-Gateway"] = "htqweb"
        return response
