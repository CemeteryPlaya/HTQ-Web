"""Pydantic schemas for the ``users`` app's HTTP layer.

Ported 1:1 from the FastAPI original (``services/user/app/api/v1/auth.py``,
which defines these inline rather than in a separate ``schemas/`` module) —
field names are kept identical because the React frontend parses them as-is.
"""

from pydantic import BaseModel


class TokenObtainRequest(BaseModel):
    """Login request. ``email`` accepts EITHER an email OR a username —
    name kept as ``email`` to match the FastAPI original's field name
    (``services/user/app/api/v1/auth.py::TokenObtainRequest``)."""

    email: str
    password: str


class TokenRefreshRequest(BaseModel):
    refresh: str


class TokenResponse(BaseModel):
    access: str
    refresh: str
    token_type: str = "Bearer"


class TokenRefreshResponse(BaseModel):
    access: str
    token_type: str = "Bearer"


class AdminSessionLoginRequest(BaseModel):
    """``POST admin-session/login`` is form-urlencoded (sqladmin login
    pages), not JSON — this schema validates the parsed ``request.POST``
    dict by hand in the view rather than through ``htqweb.http.api_view``'s
    JSON ``body=`` machinery."""

    username: str
    password: str
    next: str = "/sqladmin/"
