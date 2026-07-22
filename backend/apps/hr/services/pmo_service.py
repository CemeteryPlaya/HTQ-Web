"""Бизнес-логика проектных офисов (PMO) — порт
services/hr/app/services/pmo_service.py.

Функции, а не класс — тот же стиль, что и department_service.py/
org_service.py этого порта (исходник был class-based только из-за DI сессии
SQLAlchemy, здесь синхронный Django ORM и сессии нет).

``get_employee_pmos`` вызывается ИЗ employees-вьюх (``GET /employees/me/pmos``,
``GET /employees/{id}/pmos``) — буквальный порт ``PMOService.get_employee_pmos``
исходника, которую зовёт РОУТЕР ``employees.py`` исходника, а не ``pmo.py``.

``select_for_update()`` (порт ``with_for_update()`` исходника) в
``_assert_no_active_duplicate``/``_assert_no_active_primary``/``delete_pmo``
требует активной транзакции — вызывающие эндпойнты (``add_member``/
``update_member``/``delete_pmo``) обёрнуты ``@transaction.atomic``.
"""
from __future__ import annotations

from datetime import date

from django.db import transaction
from django.db.models import BooleanField, Case, Q, Sum, Value, When

from apps.hr.models import Employee, PMO, PMOMember


class PMONotFound(Exception):
    """404 {"detail": "PMO not found"}."""


class PMOCodeExists(Exception):
    """409: код PMO уже занят."""

    def __init__(self, code: str) -> None:
        self.detail = f"PMO with code '{code}' already exists"
        super().__init__(self.detail)


class PMOClosed(Exception):
    """409: попытка добавить участника в закрытый PMO."""

    detail = "Cannot add members to a closed PMO"

    def __init__(self) -> None:
        super().__init__(self.detail)


class EmployeeNotFound(Exception):
    """404 {"detail": "Employee not found"} — employee_id участника не существует."""


class PMOMemberNotFound(Exception):
    """404 {"detail": "Member not found in this PMO"}."""


class PMOMemberDatesInvalid(Exception):
    """422: to_date < from_date."""

    detail = "to_date must be >= from_date"

    def __init__(self) -> None:
        super().__init__(self.detail)


class PMOMemberDuplicateActive(Exception):
    """409: сотрудник уже активный участник этого PMO."""

    detail = "Employee is already an active member of this PMO"

    def __init__(self) -> None:
        super().__init__(self.detail)


class PMOMemberPrimaryExists(Exception):
    """409: у PMO уже есть активный первичный участник."""

    detail = "PMO already has a primary member"

    def __init__(self) -> None:
        super().__init__(self.detail)


# ── сериализаторы (формы из pmo.py роутера исходника) ────────────────────

def serialize(pmo: PMO) -> dict:
    """PMOOut."""
    return {
        "id": pmo.id,
        "name": pmo.name,
        "code": pmo.code,
        "description": pmo.description,
        "head_employee_id": pmo.head_employee_id,
        "status": pmo.status,
    }


def serialize_member_created(member: PMOMember) -> dict:
    """MemberCreatedOut — форма ответа POST/PATCH .../members[/...]."""
    return {
        "id": member.id,
        "pmo_id": member.pmo_id,
        "employee_id": member.employee_id,
        "membership_type": member.membership_type,
        "position_in_pmo": member.position_in_pmo,
        "allocation_percent": member.allocation_percent,
        "is_primary": member.is_primary,
        "from_date": member.from_date.isoformat() if member.from_date else None,
        "to_date": member.to_date.isoformat() if member.to_date else None,
    }


def _active_member_q(today: date) -> Q:
    """Порт _active_member_clause: from_date <= today AND (to_date IS NULL OR to_date >= today)."""
    return Q(from_date__lte=today) & (Q(to_date__isnull=True) | Q(to_date__gte=today))


# ── PMO CRUD ────────────────────────────────────────────────────────────

def list_pmos(*, status_filter: str | None = None) -> list[dict]:
    qs = PMO.objects.all()
    if status_filter:
        qs = qs.filter(status=status_filter)
    return [serialize(p) for p in qs.order_by("name")[:500]]


def get_pmo(id: int) -> PMO:
    pmo = PMO.objects.filter(id=id).first()
    if pmo is None:
        raise PMONotFound
    return pmo


def create_pmo(data: dict) -> PMO:
    if PMO.objects.filter(code=data["code"]).exists():
        raise PMOCodeExists(data["code"])
    return PMO.objects.create(**data)


@transaction.atomic
def update_pmo(id: int, data: dict) -> PMO:
    # Странность исходника, сохранена буквально: PATCH со status="closed" не
    # обновляет status полем как остальные — редиректит в delete_pmo (soft
    # close + закрытие активных членств), затем перечитывает PMO.
    if data.get("status") == "closed":
        delete_pmo(id)
        return get_pmo(id)
    pmo = get_pmo(id)
    for field, value in data.items():
        setattr(pmo, field, value)
    if data:
        pmo.save()
    return pmo


@transaction.atomic
def delete_pmo(id: int) -> None:
    """Порт delete_pmo исходника: НЕ физическое удаление — PMO переводится в
    status="closed", и все ТЕКУЩИЕ активные членства получают to_date=today."""
    pmo = get_pmo(id)
    pmo.status = "closed"
    pmo.save(update_fields=["status"])
    today = date.today()
    members = list(
        PMOMember.objects.select_for_update().filter(pmo_id=id).filter(_active_member_q(today))
    )
    for member in members:
        member.to_date = today
        member.save(update_fields=["to_date"])


# ── Members ─────────────────────────────────────────────────────────────

def list_members(pmo_id: int) -> list[dict]:
    get_pmo(pmo_id)  # 404-гейт — буквально как исходник (list_members тоже проверяет существование PMO)
    qs = (
        PMOMember.objects.filter(pmo_id=pmo_id)
        .select_related("employee", "employee__position")
        # Порт order_by(to_date.is_not(None), from_date.desc(), last_name):
        # открытые членства (to_date IS NULL) идут первыми.
        .annotate(_closed=Case(
            When(to_date__isnull=True, then=Value(False)),
            default=Value(True),
            output_field=BooleanField(),
        ))
        .order_by("_closed", "-from_date", "employee__last_name")
    )
    return [
        {
            "id": m.id,
            "pmo_id": m.pmo_id,
            "employee_id": m.employee_id,
            "employee_name": f"{m.employee.first_name} {m.employee.last_name}",
            "employee_email": m.employee.email,
            "primary_position": m.employee.position.title if m.employee.position_id else None,
            "position_in_pmo": m.position_in_pmo,
            "membership_type": m.membership_type,
            "allocation_percent": m.allocation_percent,
            "is_primary": m.is_primary,
            "from_date": m.from_date.isoformat() if m.from_date else None,
            "to_date": m.to_date.isoformat() if m.to_date else None,
        }
        for m in qs
    ]


def _validate_member_dates(from_date: date, to_date: date | None) -> None:
    if to_date is not None and to_date < from_date:
        raise PMOMemberDatesInvalid


def _assert_no_active_duplicate(*, pmo_id: int, employee_id: int, exclude_member_id: int | None = None) -> None:
    today = date.today()
    qs = (
        PMOMember.objects.select_for_update()
        .filter(pmo_id=pmo_id, employee_id=employee_id)
        .filter(_active_member_q(today))
    )
    if exclude_member_id is not None:
        qs = qs.exclude(id=exclude_member_id)
    if qs.exists():
        raise PMOMemberDuplicateActive


def _assert_no_active_primary(*, pmo_id: int, exclude_member_id: int | None = None) -> None:
    today = date.today()
    qs = (
        PMOMember.objects.select_for_update()
        .filter(pmo_id=pmo_id, is_primary=True)
        .filter(_active_member_q(today))
    )
    if exclude_member_id is not None:
        qs = qs.exclude(id=exclude_member_id)
    if qs.exists():
        raise PMOMemberPrimaryExists


def _get_member(pmo_id: int, member_id: int) -> PMOMember:
    member = PMOMember.objects.filter(id=member_id, pmo_id=pmo_id).first()
    if member is None:
        raise PMOMemberNotFound
    return member


@transaction.atomic
def add_member(pmo_id: int, data: dict, *, actor_user_id: int | None = None) -> tuple[PMOMember, int]:
    pmo = get_pmo(pmo_id)
    if pmo.status == "closed":
        raise PMOClosed
    if not Employee.objects.filter(id=data["employee_id"]).exists():
        raise EmployeeNotFound

    from_date = data.get("from_date") or date.today()
    to_date = data.get("to_date")
    _validate_member_dates(from_date, to_date)
    today = date.today()
    if from_date <= today and (to_date is None or to_date >= today):
        _assert_no_active_duplicate(pmo_id=pmo_id, employee_id=data["employee_id"])
        if data.get("is_primary", False):
            _assert_no_active_primary(pmo_id=pmo_id)

    member = PMOMember.objects.create(
        pmo_id=pmo_id,
        employee_id=data["employee_id"],
        membership_type=data.get("membership_type", "permanent"),
        position_in_pmo=data.get("position_in_pmo"),
        from_date=from_date,
        to_date=to_date,
        allocation_percent=data.get("allocation_percent", 100),
        is_primary=data.get("is_primary", False),
    )
    total = employee_total_allocation(member.employee_id)
    return member, total


@transaction.atomic
def update_member(
    pmo_id: int, member_id: int, data: dict, *, actor_user_id: int | None = None,
) -> tuple[PMOMember, int]:
    member = _get_member(pmo_id, member_id)
    employee_id = data.get("employee_id", member.employee_id)
    if employee_id != member.employee_id and not Employee.objects.filter(id=employee_id).exists():
        raise EmployeeNotFound

    from_date = data.get("from_date", member.from_date)
    to_date = data.get("to_date", member.to_date)
    _validate_member_dates(from_date, to_date)

    today = date.today()
    will_be_active = from_date <= today and (to_date is None or to_date >= today)
    if will_be_active:
        _assert_no_active_duplicate(pmo_id=pmo_id, employee_id=employee_id, exclude_member_id=member_id)
        if data.get("is_primary", member.is_primary):
            _assert_no_active_primary(pmo_id=pmo_id, exclude_member_id=member_id)

    for key, value in data.items():
        if hasattr(member, key):
            setattr(member, key, value)
    member.save()
    total = employee_total_allocation(member.employee_id)
    return member, total


@transaction.atomic
def remove_member(pmo_id: int, member_id: int) -> None:
    member = _get_member(pmo_id, member_id)
    today = date.today()
    if member.to_date is None or member.to_date >= today:
        member.to_date = today if member.from_date <= today else member.from_date
        member.save(update_fields=["to_date"])


def employee_total_allocation(employee_id: int) -> int:
    today = date.today()
    total = (
        PMOMember.objects.filter(employee_id=employee_id, pmo__status="active")
        .filter(_active_member_q(today))
        .aggregate(total=Sum("allocation_percent"))["total"]
    )
    return int(total or 0)


def get_employee_pmos(employee_id: int) -> list[dict]:
    if not Employee.objects.filter(id=employee_id).exists():
        raise EmployeeNotFound
    today = date.today()
    qs = (
        PMOMember.objects.filter(employee_id=employee_id, pmo__status="active")
        .filter(_active_member_q(today))
        .select_related("pmo")
        .order_by("pmo__name")
    )
    return [
        {
            "pmo_id": m.pmo_id,
            "pmo_name": m.pmo.name,
            "pmo_code": m.pmo.code,
            "pmo_status": m.pmo.status,
            "membership_type": m.membership_type,
            "position_in_pmo": m.position_in_pmo,
            "allocation_percent": m.allocation_percent,
            "is_primary": m.is_primary,
            "from_date": m.from_date.isoformat() if m.from_date else None,
            "to_date": m.to_date.isoformat() if m.to_date else None,
        }
        for m in qs
    ]


# ── PMO org-chart ───────────────────────────────────────────────────────

def get_pmo_org_chart(pmo_id: int) -> dict:
    pmo = get_pmo(pmo_id)
    members = list_members(pmo_id)

    nodes = [
        {
            "id": f"pmo_{pmo.id}",
            "label": pmo.name,
            "type": "pmo",
            "unit_type": "pmo",
            "level": None,
            "weight": None,
            "meta": {"code": pmo.code, "status": pmo.status},
        }
    ]
    edges = []

    for m in members:
        nodes.append({
            "id": f"emp_{m['employee_id']}",
            "label": m["employee_name"],
            "type": "employee",
            "unit_type": None,
            "level": None,
            "weight": None,
            "meta": {
                "membership_type": m["membership_type"],
                "position_title": m["position_in_pmo"] or m["primary_position"],
                "allocation_percent": m["allocation_percent"],
                "is_primary": m["is_primary"],
            },
        })
        edges.append({
            "source": f"pmo_{pmo.id}",
            "target": f"emp_{m['employee_id']}",
            "relation_type": m["membership_type"],
        })

    return {"nodes": nodes, "edges": edges}
