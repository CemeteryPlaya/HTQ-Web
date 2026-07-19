"""Pydantic schemas for the ``users`` app's HTTP layer.

Ported 1:1 from the FastAPI original (``services/user/app/api/v1/auth.py``,
which defines these inline rather than in a separate ``schemas/`` module) —
field names are kept identical because the React frontend parses them as-is.
"""

from pydantic import BaseModel, Field


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


class ChangePasswordRequest(BaseModel):
    """``POST profile/change-password`` payload.

    Ported verbatim from ``services/user/app/api/v1/profile.py::
    ChangePasswordRequest`` — ``current_password`` is required for ordinary
    voluntary changes; when ``User.must_change_password`` is true (admin-
    forced reset), the current-password check is relaxed (enforced in
    ``apps.users.services.profile_service.change_password``, not here).
    """

    new_password: str = Field(..., min_length=8)
    current_password: str | None = None


# ── Registration + moderation (Task 2.4) ────────────────────────────────────
#
# Ported from ``services/user/app/api/v1/registration.py``'s inline schemas
# (the FastAPI original defines these in the router module too, not a
# separate ``schemas/`` package).


class RegisterRequest(BaseModel):
    """``POST register/`` — self-registration request.

    No format/length validation beyond "required string" — the FastAPI
    original's ``RegisterRequest`` doesn't add stricter Pydantic
    constraints either (``email: str``, not ``EmailStr``).
    """

    email: str
    password: str
    full_name: str  # split into first_name + last_name — see registration_service


class RegisterResponse(BaseModel):
    id: int
    email: str
    message: str = "Registration submitted. Awaiting admin approval."


class PendingUserResponse(BaseModel):
    id: int
    email: str
    username: str
    full_name: str
    date_joined: str


# ── Admin: user management (Task 2.4) ───────────────────────────────────────
#
# Ported from ``services/user/app/api/v1/admin.py``'s inline schemas.


class AdminUserResponse(BaseModel):
    """``GET/POST/PATCH admin/users/*`` — admin-facing user view.

    Both snake_case and camelCase name fields are present — ported verbatim
    from the FastAPI original (the React admin UI reads snake_case;
    camelCase kept for parity/forward-compat, same reasoning as
    ``apps.users.services.profile_service.build_response``).
    """

    id: int
    username: str
    email: str
    first_name: str
    last_name: str
    firstName: str
    lastName: str
    patronymic: str
    display_name: str
    bio: str
    phone: str
    avatar_url: str | None
    avatarUrl: str | None
    settings: dict
    roles: list[str]
    status: str
    is_staff: bool
    is_superuser: bool
    must_change_password: bool
    date_joined: str
    last_login: str | None
    created_at: str | None
    updated_at: str | None


class AdminUserCreateRequest(BaseModel):
    """``POST admin/users/`` — manual user creation, bypassing self-registration.

    Ported from the FastAPI original's ``AdminUserCreateRequest``, including
    the Mailcow mailbox-provisioning fields (``create_mailbox``,
    ``mailbox_local_part``, ``mailbox_password``, ``mailbox_quota_mb``) for
    request-shape parity with the frontend (``UserEditDialog.tsx`` always
    sends them). The actual provisioning (an S2S call to email-service) is
    dropped per decision Р3 ("no S2S") — see
    ``apps.users.services.admin_service``'s module docstring and the task
    2.4 report. These fields are accepted but INERT: when
    ``create_mailbox`` is true, ``apps.users.views._admin_create_user``
    returns a non-null ``mailbox_error`` instead of silently doing nothing.
    """

    username: str = Field(..., min_length=1, max_length=150)
    email: str = Field(..., min_length=3, max_length=254)
    password: str = Field(..., min_length=8)
    first_name: str = ""
    last_name: str = ""
    patronymic: str = ""
    display_name: str = ""
    bio: str = ""
    phone: str = ""
    status: str = "active"
    is_staff: bool = False
    is_superuser: bool = False
    # Default ON: admin sets a temp password, user changes it on first login.
    must_change_password: bool = True
    # Mailcow mailbox provisioning — accepted, inert (see class docstring).
    create_mailbox: bool = False
    mailbox_local_part: str | None = None
    mailbox_password: str | None = None
    mailbox_quota_mb: int = 0


class AdminUserCreatedResponse(AdminUserResponse):
    """``POST admin/users/`` response — ``AdminUserResponse`` plus the
    mailbox-provisioning outcome. Mirrors the source's
    ``AdminUserCreatedResponse`` shape so the frontend's existing
    ``created.mailbox`` / ``created.mailbox_error`` branches
    (``UserEditDialog.tsx:181-197``) work unchanged.

    ``mailbox`` is always ``None`` in this port — no provisioning ever
    happens (see ``AdminUserCreateRequest`` docstring, decision Р3).
    ``mailbox_error`` is set to an explanatory message when the admin asked
    for a mailbox (``create_mailbox=True``); ``None`` otherwise.
    """

    mailbox: dict | None = None
    mailbox_error: str | None = None


class AdminUserUpdateRequest(BaseModel):
    """``PATCH admin/users/{id}/`` — partial update; unset fields are ignored
    (``exclude_unset=True`` at the view layer). No password field — password
    changes go through ``AdminSetPasswordRequest`` instead, same split as
    the FastAPI original."""

    # Identity (admin can rename — HR rare-but-needed case).
    username: str | None = None
    email: str | None = None
    # Role / status flags
    is_staff: bool | None = None
    is_superuser: bool | None = None
    status: str | None = None
    must_change_password: bool | None = None
    # Profile fields — admins can edit on a user's behalf (HR /hr/profiles).
    display_name: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    patronymic: str | None = None
    bio: str | None = None
    phone: str | None = None
    avatar_url: str | None = None
    settings: dict | str | None = None  # JSON object or stringified JSON


class AdminSetPasswordRequest(BaseModel):
    """``POST admin/users/{id}/set-password/`` — admin-initiated password
    reset; does not require the user's old password."""

    new_password: str = Field(..., min_length=8)
    must_change_password: bool = True


# ── Items (Task 2.5) ─────────────────────────────────────────────────────────
#
# Ported from ``services/user/app/api/v1/items.py``'s inline schemas.


class ItemResponse(BaseModel):
    id: int
    title: str
    description: str
    owner_id: int
    created_at: str


class ItemCreateRequest(BaseModel):
    title: str
    description: str = ""


class ItemUpdateRequest(BaseModel):
    title: str | None = None
    description: str | None = None


# ── Client telemetry (Task 2.5) ─────────────────────────────────────────────
#
# Ported from ``services/user/app/api/v1/client_errors.py``'s inline schemas.
# Field names are camelCase where the FastAPI original used camelCase
# (``componentStack``, ``userAgent``, ``userId``, ``resourceId``) — kept
# identical because ``frontend/src/lib/telemetry.ts`` sends these as-is.


class ClientErrorReport(BaseModel):
    message: str
    stack: str | None = None
    componentStack: str | None = None
    url: str
    userAgent: str | None = None
    userId: int | None = None
    timestamp: str | None = None


class UserActionEvent(BaseModel):
    action: str
    resource: str | None = None
    resourceId: str | int | None = None
    meta: dict | None = None
    url: str
    userAgent: str | None = None
    timestamp: str | None = None


# ── User options (Task 2.5) ─────────────────────────────────────────────────
#
# Ported from ``services/user/app/api/v1/users.py``'s inline schemas.


class UserOption(BaseModel):
    id: int
    full_name: str
    email: str


class UserOptionsQuery(BaseModel):
    """Validates ``GET users/options/`` query params — mirrors the FastAPI
    original's ``Query(default=200, ge=1, le=500)`` so an out-of-range
    ``limit`` 422s instead of being silently clamped."""

    query: str | None = None
    limit: int = Field(200, ge=1, le=500)
