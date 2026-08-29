"""Выдача ролей: должности (штатный путь) и лично пользователю (исключение).

⚠️ Каждая выборка здесь несёт ``company_slug``. Таблицы лежат в ``public``, и
``search_path`` их НЕ изолирует: замена набора без фильтра стёрла бы
назначения соседней компании, не выглядя ошибкой (спека §1.3, риск 3).
Сторож — ``apps/access/tests/test_guards.py``.
"""

from __future__ import annotations

from django.db import transaction

from apps.access.models import PositionRole, Role, RoleAssignment, ScopeKind
from apps.access.services.errors import ScopeInvalid, UnknownRole


def _check_roles_exist(role_ids: list[int]) -> None:
    wanted = set(role_ids)
    if not wanted:
        return
    known = set(Role.objects.filter(id__in=wanted).values_list("id", flat=True))
    missing = sorted(wanted - known)
    if missing:
        raise UnknownRole(f"нет таких ролей: {missing}")


def position_roles(company: str, position_id: int) -> list[dict]:
    return [
        {"role_id": row["role_id"], "code": row["role__code"], "title": row["role__title"]}
        for row in (PositionRole.objects
                    .filter(company_slug=company, position_id=position_id)
                    .order_by("role__title")
                    .values("role_id", "role__code", "role__title"))
    ]


def set_position_roles(company: str, position_id: int, role_ids: list[int]) -> None:
    """Замена набора ролей должности целиком (спека §4.3)."""
    unique_ids = list(dict.fromkeys(role_ids))
    _check_roles_exist(unique_ids)
    with transaction.atomic():
        PositionRole.objects.filter(
            company_slug=company, position_id=position_id).delete()
        PositionRole.objects.bulk_create([
            PositionRole(company_slug=company, position_id=position_id, role_id=rid)
            for rid in unique_ids
        ])


def _check_scope(item: dict) -> None:
    kind, scope_id = item.get("scope_kind"), item.get("scope_id")
    if kind not in ScopeKind.values:
        raise ScopeInvalid(f"неизвестная область: {kind!r}")
    if kind == ScopeKind.COMPANY and scope_id is not None:
        raise ScopeInvalid("область «компания» не имеет идентификатора")
    if kind != ScopeKind.COMPANY and scope_id is None:
        raise ScopeInvalid(f"область {kind!r} требует scope_id")


def user_assignments(company: str, user_id: int) -> list[dict]:
    return [
        {"role_id": row["role_id"], "scope_kind": row["scope_kind"],
         "scope_id": row["scope_id"]}
        for row in (RoleAssignment.objects
                    .filter(company_slug=company, user_id=user_id)
                    .order_by("role_id", "scope_kind")
                    .values("role_id", "scope_kind", "scope_id"))
    ]


def set_user_assignments(company: str, user_id: int, items: list[dict]) -> None:
    """Замена личных назначений целиком (спека §4.4).

    Исключительный путь: не-сотрудники, исполняющие обязанности, временные
    расширения. Штатный — роли должности.
    """
    for item in items:
        _check_scope(item)
    _check_roles_exist([i["role_id"] for i in items])

    seen: set[tuple] = set()
    rows: list[RoleAssignment] = []
    for item in items:
        key = (item["role_id"], item["scope_kind"], item["scope_id"])
        if key in seen:
            continue
        seen.add(key)
        rows.append(RoleAssignment(
            company_slug=company, user_id=user_id, role_id=item["role_id"],
            scope_kind=item["scope_kind"], scope_id=item["scope_id"],
        ))

    with transaction.atomic():
        RoleAssignment.objects.filter(company_slug=company, user_id=user_id).delete()
        RoleAssignment.objects.bulk_create(rows)
