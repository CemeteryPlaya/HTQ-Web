"""Employees API router.

Route ordering matters: literal-segment endpoints (`/users/`, `/hr-level/`)
MUST be declared before the catch-all `/{id}/`, otherwise FastAPI tries to
parse `users` / `hr-level` as an int and 422s.
"""

from typing import Literal

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import settings
from app.db import get_db_session
from app.auth.dependencies import get_current_user, TokenPayload
from app.auth.hr_access import (
    HRAccess,
    HRLevel,
    require_can_write_basic,
    require_hr_access,
    resolve_hr_access,
)
from app.models.employee import Employee
from app.schemas.employee import EmployeeCreate, EmployeeUpdate, EmployeeOut, EmployeeTransfer
from app.schemas.common import PaginatedResponse
from app.services.employee_card_service import EmployeeCardService
from app.services.employee_service import EmployeeService
from app.services.pmo_service import PMOService

router = APIRouter(prefix="/employees", tags=["employees"])
logger = structlog.get_logger()


def _svc(db: AsyncSession = Depends(get_db_session)) -> EmployeeService:
    return EmployeeService(db)


# ─── Literal-segment endpoints (MUST come BEFORE /{id}/) ────────────────────

class HRUserOption(BaseModel):
    """Compact user record used by the "create employee from user" picker.

    Carries ``first_name`` / ``last_name`` separately so the create-employee
    form can prefill them into the EmployeeCreate payload (the schema demands
    them as required fields, separate from the picker's display label).
    """

    id: int
    full_name: str
    email: str
    first_name: str = ""
    last_name: str = ""


class HRLevelResponse(BaseModel):
    level: HRLevel | None
    scope_department_id: int | None = None
    can_read_all: bool = False
    can_write_basic: bool = False
    can_create_employee: bool = False
    can_transfer_employee: bool = False
    can_delete_employee: bool = False
    can_list_user_options: bool = False
    can_manage_user_options: bool = False
    permissions: list[str] = []


class EmployeePmoOut(BaseModel):
    pmo_id: int
    pmo_name: str
    pmo_code: str
    pmo_status: str
    membership_type: str
    position_in_pmo: str | None
    allocation_percent: int
    is_primary: bool
    from_date: str | None
    to_date: str | None


@router.get("/users/", response_model=list[HRUserOption])
async def list_user_options(
    db: AsyncSession = Depends(get_db_session),
    current_user: TokenPayload = Depends(get_current_user),
):
    """Return all platform users as id/full_name/email pairs.

    Drives the user-selector in /hr/employees create dialog. We proxy
    `user-service /api/users/v1/admin/users/` instead of replicating the
    user list locally — admin token is forwarded as-is.
    """
    access = require_hr_access(await resolve_hr_access(db, current_user))
    if not access.can_list_user_options:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Senior HR access required")

    user_service_url = getattr(settings, "user_service_url", "http://user-service:8005")
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            # We rely on user-service's RBAC (admin only). Forward the
            # caller's JWT so the audit log lands under the right user_id.
            # For non-admin callers the upstream returns 403, propagated.
            # The current request's Authorization header is already validated
            # by get_current_user; re-issue a fresh token isn't necessary —
            # we synthesise an internal payload via shared JWT secret.
            import jwt as _jwt
            import datetime as _dt
            now = _dt.datetime.now(_dt.timezone.utc)
            internal = _jwt.encode(
                {
                    "user_id": current_user.user_id,
                    "username": current_user.username or "",
                    "email": current_user.email or "",
                    "is_staff": current_user.is_staff,
                    "is_superuser": current_user.is_superuser,
                    "is_admin": current_user.is_admin,
                    "token_type": "access",
                    "iat": now,
                    "exp": now + _dt.timedelta(minutes=2),
                    "iss": settings.jwt_issuer,
                },
                settings.jwt_secret,
                algorithm=settings.jwt_algorithm,
            )
            resp = await client.get(
                f"{user_service_url}/api/users/v1/admin/users/",
                headers={"Authorization": f"Bearer {internal}"},
            )
    except httpx.HTTPError as exc:
        logger.warning("hr_users_proxy_failed", err=str(exc))
        return []

    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail="user-service unavailable")

    users = resp.json() if isinstance(resp.json(), list) else resp.json().get("items", [])
    out: list[HRUserOption] = []
    for u in users:
        first = u.get("first_name") or u.get("firstName") or ""
        last = u.get("last_name") or u.get("lastName") or ""
        patronymic = u.get("patronymic") or ""
        full_name = (f"{first} {last}".strip() or u.get("display_name") or u.get("username") or "").strip()
        out.append(
            HRUserOption(
                id=u["id"],
                full_name=full_name,
                email=u.get("email") or "",
                first_name=first,
                last_name=last,
            )
        )
    return out


class HRUserCreateRequest(BaseModel):
    """Lightweight user creation triggered from the HR employee dialog.

    The HR side only knows ФИО + email; we don't ask the admin for a username
    or password — those are derived locally and the user is required to change
    the password on first login.
    """

    first_name: str = ""
    last_name: str = ""
    patronymic: str = ""
    email: str


def _build_internal_jwt(current_user: TokenPayload) -> str:
    """Mint a short-lived internal JWT to call user-service from hr-service."""
    import datetime as _dt

    import jwt as _jwt

    now = _dt.datetime.now(_dt.timezone.utc)
    return _jwt.encode(
        {
            "user_id": current_user.user_id,
            "username": current_user.username or "",
            "email": current_user.email or "",
            "is_staff": current_user.is_staff,
            "is_superuser": current_user.is_superuser,
            "is_admin": current_user.is_admin,
            "token_type": "access",
            "iat": now,
            "exp": now + _dt.timedelta(minutes=2),
            "iss": settings.jwt_issuer,
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )


@router.post("/users/", response_model=HRUserOption, status_code=status.HTTP_201_CREATED)
async def create_user_option(
    body: HRUserCreateRequest,
    db: AsyncSession = Depends(get_db_session),
    current_user: TokenPayload = Depends(get_current_user),
):
    """Create a new platform user from the HR side and return it as an option.

    Derives ``username`` from the email's local part (collision-safe via the
    upstream uniqueness check), generates a temporary password, and forwards to
    user-service ``POST /api/users/v1/admin/users/``. ``must_change_password``
    is true so the new user must rotate the temp password on first login.
    """
    import secrets

    access = require_hr_access(await resolve_hr_access(db, current_user))
    if not access.can_manage_user_options:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CO HR access required")

    email = (body.email or "").strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=422, detail="Email обязателен и должен быть валидным")

    username_base = email.split("@", 1)[0] or "user"
    # Strip anything that's not safe for usernames; collisions are surfaced by
    # the upstream service rather than guessed locally.
    username = "".join(ch for ch in username_base if ch.isalnum() or ch in {".", "_", "-"})[:32] or "user"

    user_service_url = getattr(settings, "user_service_url", "http://user-service:8005")
    payload = {
        "username": username,
        "email": email,
        "password": secrets.token_urlsafe(12),
        "first_name": body.first_name or "",
        "last_name": body.last_name or "",
        "patronymic": body.patronymic or "",
        "display_name": f"{body.first_name} {body.last_name}".strip() or username,
        "status": "active",
        "must_change_password": True,
    }

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                f"{user_service_url}/api/users/v1/admin/users/",
                json=payload,
                headers={"Authorization": f"Bearer {_build_internal_jwt(current_user)}"},
            )
    except httpx.HTTPError as exc:
        logger.warning("hr_users_create_proxy_failed", err=str(exc))
        raise HTTPException(status_code=502, detail="user-service unavailable")

    if resp.status_code == 400:
        # Surface upstream validation errors (e.g. email/username already in use).
        try:
            detail = resp.json().get("detail") or "Пользователь с такими данными уже существует"
        except Exception:
            detail = "Пользователь с такими данными уже существует"
        raise HTTPException(status_code=409, detail=detail)
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail="user-service create failed")

    data = resp.json()
    full_name = (
        f"{data.get('first_name') or ''} {data.get('last_name') or ''}".strip()
        or data.get("display_name")
        or data.get("username")
        or ""
    )
    return HRUserOption(
        id=data["id"],
        full_name=full_name,
        email=data.get("email") or email,
        username=data.get("username") or "",
        first_name=data.get("first_name") or "",
        last_name=data.get("last_name") or "",
        patronymic=data.get("patronymic") or "",
    )


@router.get("/hr-level/", response_model=HRLevelResponse)
async def get_my_hr_level(
    db: AsyncSession = Depends(get_db_session),
    current_user: TokenPayload = Depends(get_current_user),
):
    """Fine-grained HR access level for the current caller."""
    access = await resolve_hr_access(db, current_user)
    return HRLevelResponse(
        level=access.level,
        scope_department_id=access.department_id,
        can_read_all=access.can_read_all,
        can_write_basic=access.can_write_basic,
        can_create_employee=access.can_create_employee,
        can_transfer_employee=access.can_transfer_employee,
        can_delete_employee=access.can_delete_employee,
        can_list_user_options=access.can_list_user_options,
        can_manage_user_options=access.can_manage_user_options,
        permissions=sorted(access.permissions),
    )


@router.get("/me/", response_model=EmployeeOut)
async def my_employee(
    db: AsyncSession = Depends(get_db_session),
    current_user: TokenPayload = Depends(get_current_user),
):
    """The caller's own Employee row — populated by HR/admin at hire time.

    The Settings page renders this read-only so users can see what HR
    currently has on file (position, department, hire date, work phone).
    Falls back to email-match because legacy rows from the Django era
    sometimes lack ``user_id``.
    """
    from sqlalchemy import or_, select
    from sqlalchemy.orm import joinedload

    stmt = select(Employee).options(
        joinedload(Employee.department), joinedload(Employee.position)
    )
    if current_user.email:
        stmt = stmt.where(
            or_(
                Employee.user_id == current_user.user_id,
                Employee.email == current_user.email,
            )
        )
    else:
        stmt = stmt.where(Employee.user_id == current_user.user_id)
    employee = (await db.execute(stmt.limit(1))).scalars().first()
    if not employee:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee profile not found")
    return employee


@router.get("/me/pmos", response_model=list[EmployeePmoOut])
async def my_pmos(
    db: AsyncSession = Depends(get_db_session),
    current_user: TokenPayload = Depends(get_current_user),
):
    from sqlalchemy import or_, select

    stmt = select(Employee)
    if current_user.email:
        stmt = stmt.where(or_(Employee.user_id == current_user.user_id, Employee.email == current_user.email))
    else:
        stmt = stmt.where(Employee.user_id == current_user.user_id)
    employee = (await db.execute(stmt.limit(1))).scalars().first()
    if not employee:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee profile not found")
    return await PMOService(db).get_employee_pmos(employee.id)


@router.get("/me/card")
async def my_employee_card(
    db: AsyncSession = Depends(get_db_session),
    current_user: TokenPayload = Depends(get_current_user),
):
    """Full employee card for the caller — drives ``MyHRCard`` on /myprofile."""
    from sqlalchemy import or_, select

    stmt = select(Employee)
    if current_user.email:
        stmt = stmt.where(
            or_(
                Employee.user_id == current_user.user_id,
                Employee.email == current_user.email,
            )
        )
    else:
        stmt = stmt.where(Employee.user_id == current_user.user_id)
    employee = (await db.execute(stmt.limit(1))).scalars().first()
    if not employee:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Employee profile not found",
        )
    access = await resolve_hr_access(db, current_user)
    return await EmployeeCardService(db).build_card(employee.id, mode="full", access=access)


@router.get("/", response_model=PaginatedResponse[EmployeeOut])
async def list_employees(
    department_id: int | None = Query(default=None),
    status: str | None = Query(default=None),
    search: str | None = Query(default=None, description="Free-text: name / email"),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=200),
    svc: EmployeeService = Depends(_svc),
    db: AsyncSession = Depends(get_db_session),
    current_user: TokenPayload = Depends(get_current_user),
):
    access = require_hr_access(await resolve_hr_access(db, current_user))
    effective_department_id = department_id
    if not access.can_read_all:
        if access.department_id is None or (
            department_id is not None and department_id != access.department_id
        ):
            return PaginatedResponse(items=[], total=0, page=page, pages=0, limit=limit)
        effective_department_id = access.department_id

    items, total = await svc.list_employees(
        department_id=effective_department_id,
        status=status,
        search=search,
        page=page,
        limit=limit,
    )
    pages = (total + limit - 1) // limit
    return PaginatedResponse(items=items, total=total, page=page, pages=pages, limit=limit)


@router.post("/", response_model=EmployeeOut, status_code=status.HTTP_201_CREATED)
async def create_employee(
    body: EmployeeCreate,
    svc: EmployeeService = Depends(_svc),
    db: AsyncSession = Depends(get_db_session),
    current_user: TokenPayload = Depends(get_current_user),
):
    access = require_hr_access(await resolve_hr_access(db, current_user))
    if not access.can_create_employee:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Senior HR access required")
    return await svc.create_employee(body, changed_by_id=current_user.user_id)


async def _require_visible_employee(id: int, svc: EmployeeService, access: HRAccess) -> Employee:
    employee = await svc.get_employee(id)
    if not access.can_see_department(employee.department_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")
    return employee


@router.get("/{id}/pmos", response_model=list[EmployeePmoOut])
async def employee_pmos(
    id: int,
    db: AsyncSession = Depends(get_db_session),
    svc: EmployeeService = Depends(_svc),
    current_user: TokenPayload = Depends(get_current_user),
):
    access = require_hr_access(await resolve_hr_access(db, current_user))
    await _require_visible_employee(id, svc, access)
    return await PMOService(db).get_employee_pmos(id)


@router.get("/{id}/card")
async def employee_card(
    id: int,
    db: AsyncSession = Depends(get_db_session),
    svc: EmployeeService = Depends(_svc),
    current_user: TokenPayload = Depends(get_current_user),
):
    """Full employee card — drives ``/hr/employees/:id`` page."""
    access = require_hr_access(await resolve_hr_access(db, current_user))
    await _require_visible_employee(id, svc, access)
    return await EmployeeCardService(db).build_card(id, mode="full", access=access)


@router.get("/{id}/", response_model=EmployeeOut)
async def get_employee(
    id: int,
    svc: EmployeeService = Depends(_svc),
    db: AsyncSession = Depends(get_db_session),
    current_user: TokenPayload = Depends(get_current_user),
):
    access = require_hr_access(await resolve_hr_access(db, current_user))
    return await _require_visible_employee(id, svc, access)


@router.put("/{id}/", response_model=EmployeeOut)
async def update_employee(
    id: int,
    body: EmployeeUpdate,
    svc: EmployeeService = Depends(_svc),
    db: AsyncSession = Depends(get_db_session),
    current_user: TokenPayload = Depends(get_current_user),
):
    access = require_can_write_basic(await resolve_hr_access(db, current_user))
    await _require_visible_employee(id, svc, access)
    if not access.can_transfer_employee and (
        body.department_id is not None
        or body.position_id is not None
        or body.termination_date is not None
        or body.status in {"terminated", "suspended", "rejected"}
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Transferring, changing position, or terminating requires the transfer permission",
        )
    return await svc.update_employee(id, body, changed_by_id=current_user.user_id)


@router.delete("/{id}/", status_code=status.HTTP_204_NO_CONTENT)
async def delete_employee(
    id: int,
    svc: EmployeeService = Depends(_svc),
    db: AsyncSession = Depends(get_db_session),
    current_user: TokenPayload = Depends(get_current_user),
):
    access = require_hr_access(await resolve_hr_access(db, current_user))
    if not access.can_delete_employee:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CO HR access required")
    await _require_visible_employee(id, svc, access)
    await svc.delete_employee(id, changed_by_id=current_user.user_id)


@router.post("/{id}/transfer", response_model=EmployeeOut)
async def transfer_employee(
    id: int,
    body: EmployeeTransfer,
    svc: EmployeeService = Depends(_svc),
    db: AsyncSession = Depends(get_db_session),
    current_user: TokenPayload = Depends(get_current_user),
):
    access = require_hr_access(await resolve_hr_access(db, current_user))
    if not access.can_transfer_employee:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Senior HR access required")
    await _require_visible_employee(id, svc, access)
    return await svc.transfer_employee(id, body, changed_by_id=current_user.user_id)


@router.get("/{id}/history")
async def employee_history(
    id: int,
    db: AsyncSession = Depends(get_db_session),
    svc: EmployeeService = Depends(_svc),
    current_user: TokenPayload = Depends(get_current_user),
):
    from sqlalchemy import select
    from app.models.audit_log import AuditLog

    access = require_hr_access(await resolve_hr_access(db, current_user))
    await _require_visible_employee(id, svc, access)

    result = await db.execute(
        select(AuditLog)
        .where(AuditLog.entity_type == "employee", AuditLog.entity_id == id)
        .order_by(AuditLog.created_at.desc())
        .limit(100)
    )
    logs = result.scalars().all()
    return [
        {
            "id": log.id,
            "action": log.action,
            "old_values": log.old_values,
            "new_values": log.new_values,
            "changed_by": log.changed_by,
            "created_at": log.created_at.isoformat(),
        }
        for log in logs
    ]


@router.get("/{id}/documents")
async def employee_documents(
    id: int,
    db: AsyncSession = Depends(get_db_session),
    svc: EmployeeService = Depends(_svc),
    current_user: TokenPayload = Depends(get_current_user),
):
    from sqlalchemy import select
    from app.models.document import Document

    access = require_hr_access(await resolve_hr_access(db, current_user))
    await _require_visible_employee(id, svc, access)

    result = await db.execute(
        select(Document).where(Document.employee_id == id).order_by(Document.created_at.desc())
    )
    return result.scalars().all()
