"""Request ID middleware — propagates X-Request-ID from gateway."""

import uuid
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response


REQUEST_ID_HEADER = "x-request-id"


class RequestIDMiddleware(BaseHTTPMiddleware):
    """
    Extract X-Request-ID from incoming request headers.
    If missing, generate a new UUID.
    Attach it to the response headers.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid.uuid4())
        request.state.request_id = request_id

        response = await call_next(request)

        response.headers[REQUEST_ID_HEADER] = request_id
        response.headers["X-Gateway"] = "htqweb"

        return response
