"""Тонкий слой ролевого доступа HR — порт services/hr/app/auth/hr_access.py.

СИНХРОННО (Django, не asyncio) и от Django-токена (``request.token`` —
``htqweb.authn.payload.TokenPayload``), а не от пары ``(db, current_user)``
исходника. Это НЕ грубый ``api_view(admin=True)`` (как в positions) — вьюхи
сами зовут ``resolve_hr_access(request.token)`` и проверяют ``access.can_*``,
поднимая нужный 403 с точным detail исходника.

``ALL_KEYS``/``expand_level`` уже перенесены в ``apps.hr.permissions`` вместе
с положениями (LEVEL_PRESETS) — переиспользуются здесь, не дублируются.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from django.db.models import Q

from apps.hr.models import Employee
from apps.hr.permissions import ALL_KEYS, expand_level

HRLevel = Literal["junior", "middle", "senior", "lead"]


class HRAccessDenied(Exception):
    """403 — вьюха превращает в {"detail": exc.detail}."""

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


@dataclass(frozen=True)
class HRAccess:
    """Резолвленный HR-скоуп текущего вызывающего.

    ``permissions`` — авторитетный набор ключей. ``level`` хранится только
    для отображения. Член ``"*"`` в ``permissions`` означает «все ключи»
    (admin-wildcard).
    """

    level: HRLevel | None
    permissions: frozenset[str] = frozenset()
    employee_id: int | None = None
    department_id: int | None = None

    def has(self, key: str) -> bool:
        return "*" in self.permissions or key in self.permissions

    @property
    def has_access(self) -> bool:
        return self.level is not None or bool(self.permissions)

    @property
    def can_read_all(self) -> bool:
        return self.has("hr.employees.view.all")

    @property
    def can_write_basic(self) -> bool:
        return self.has("hr.employees.edit")

    @property
    def can_create_employee(self) -> bool:
        return self.has("hr.employees.create")

    @property
    def can_transfer_employee(self) -> bool:
        return self.has("hr.employees.transfer")

    @property
    def can_delete_employee(self) -> bool:
        return self.has("hr.employees.delete")

    @property
    def can_manage_user_options(self) -> bool:
        return self.has("hr.users.manage")

    @property
    def can_list_user_options(self) -> bool:
        return self.has("hr.users.list")

    @property
    def can_view_identity_requests(self) -> bool:
        return self.has("hr.identity.view")

    @property
    def can_manage_identity_approver(self) -> bool:
        return self.has("hr.identity.manage")

    def can_see_department(self, department_id: int | None) -> bool:
        if self.can_read_all:
            return True
        return self.department_id is not None and department_id == self.department_id


def _normalize(value: str | None) -> str:
    return (value or "").strip().lower().replace("_", " ").replace("-", " ")


_VALID_LEVELS: set[str] = {"junior", "middle", "senior", "lead"}


def _level_from_permissions(position) -> HRLevel | None:
    """Явный ``permissions.hr_level`` должности приоритетнее эвристики.

    ``Position.permissions`` заполняется админами через HR UI и переопределяет
    эвристику по названию — так пользовательская должность («Специалист по
    обучению») может получить middle/senior HR-доступ без придумывания
    системного названия.
    """
    perms = getattr(position, "permissions", None)
    if not isinstance(perms, dict):
        return None
    hr_level = perms.get("hr_level")
    if hr_level in _VALID_LEVELS:
        return hr_level  # type: ignore[return-value]
    return None


def classify_hr_level(employee: Employee | None) -> HRLevel | None:
    """Эвристика по HR-отделу/должности сотрудника.

    Порядок разрешения:
    1. ``position.permissions.hr_level`` — явный оверрайд.
    2. Эвристика по названию/отделу — legacy-фолбэк для системных должностей.

    Строковые маркеры — БУКВАЛЬНЫЙ порт (влияют на выдачу прав).
    """
    if not employee:
        return None

    explicit = _level_from_permissions(getattr(employee, "position", None))
    if explicit is not None:
        return explicit

    position = _normalize(getattr(employee.position, "title", None))
    department = _normalize(getattr(employee.department, "name", None))
    haystack = f"{position} {department}"

    is_hr = any(
        marker in haystack
        for marker in (
            "hr",
            "human resources",
            "people",
            "персонал",
            "кадр",
            "эйчар",
        )
    )
    if not is_hr:
        return None

    if any(
        marker in haystack
        for marker in (
            "co hr",
            "cohr",
            "chief hr",
            "chief human resources",
            "chief people",
            "cpo",
            "hr director",
            "director hr",
            "руководитель hr",
            "директор по персоналу",
        )
    ):
        return "lead"

    if any(marker in haystack for marker in ("senior", "lead", "head", "старш", "ведущ")):
        return "senior"

    if any(marker in haystack for marker in ("middle", "middel", "mid ", "manager", "менеджер", "специалист")):
        return "middle"

    if any(marker in haystack for marker in ("junior", "assistant", "trainee", "младш", "ассист", "стаж")):
        return "junior"

    return "junior"


def resolve_hr_access(token) -> HRAccess:
    """Резолвит HR-доступ вызывающего из JWT-токена и HR-профиля Employee.

    ``token`` — ``htqweb.authn.payload.TokenPayload`` (``request.token``,
    заполняется ``api_view(auth="jwt")``). ``token.is_elevated`` — тот же
    предикат, что ``current_user.is_admin or is_staff or is_superuser``
    исходника (см. htqweb/authn/payload.py::TokenPayload.is_elevated).
    """
    if token.is_elevated:
        return HRAccess(level="lead", permissions=frozenset({"*"}))

    qs = Employee.objects.filter(is_deleted=False).select_related("department", "position")
    if token.email:
        qs = qs.filter(Q(user_id=token.user_id) | Q(email=token.email))
    else:
        qs = qs.filter(user_id=token.user_id)
    employee = qs.first()

    level = classify_hr_level(employee)
    position = getattr(employee, "position", None) if employee else None
    raw = getattr(position, "permissions", None)
    if isinstance(raw, dict) and isinstance(raw.get("permissions"), list) and raw["permissions"]:
        perms = frozenset(str(p) for p in raw["permissions"]) & ALL_KEYS
    else:
        perms = expand_level(level)

    return HRAccess(
        level=level,
        permissions=perms,
        employee_id=employee.id if employee else None,
        department_id=employee.department_id if employee else None,
    )


def require_hr_access(access: HRAccess) -> HRAccess:
    if not access.has_access:
        raise HRAccessDenied("HR access required")
    return access


def require_can_write_basic(access: HRAccess) -> HRAccess:
    require_hr_access(access)
    if not access.can_write_basic:
        raise HRAccessDenied("HR write access required")
    return access
