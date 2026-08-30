"""Каталог ролей — операции платформенного уровня (спека §4.1, §4.2).

Каталог ОДИН на все компании, поэтому правка роли меняет доступ везде сразу и
обратной силы у ошибки нет. Отсюда две особенности этого модуля: уникальность
кода проверяется по всей платформе, а удаление занятой роли отвергается с
числом затронутых должностей и пользователей вместо тихого снятия прав.

Права роли проверяет вьюха (``is_superuser``), а не сервис: сервис вызывается
и из django-admin, и из будущих команд, где понятия «текущий пользователь» нет.
"""

from __future__ import annotations

from django.db import IntegrityError, transaction

from apps.access import depth, registry
from apps.access.models import Role, RolePermission
from apps.access.services.errors import (
    DepthNotApplicable,
    RoleConflict,
    RoleInUse,
    RoleIsSystem,
    UnknownModule,
)


def create_role(code: str, title: str) -> Role:
    try:
        with transaction.atomic():
            return Role.objects.create(code=code, title=title)
    except IntegrityError as exc:
        raise RoleConflict(code) from exc


def rename_role(role_id: int, title: str) -> Role:
    role = Role.objects.get(id=role_id)
    role.title = title
    role.save(update_fields=["title", "updated_at"])
    return role


def delete_role(role_id: int) -> None:
    role = Role.objects.get(id=role_id)
    if role.is_system:
        raise RoleIsSystem(role.code)
    # Занятость считается по ВСЕЙ платформе, а не по текущей компании: роль
    # одна на всех, и удаление в одной компании отняло бы права в остальных.
    positions = role.position_links.count()
    users = role.assignments.count()
    if positions or users:
        raise RoleInUse(positions=positions, users=users)
    role.delete()


def permissions_of(role_id: int) -> list[dict]:
    """Явно заданная глубина роли по узлам, в порядке реестра.

    Отдаются и флаги, и название пресета, если набор совпал с известным:
    интерфейсу нужно показать «может редактировать», а не четыре галочки, но
    своя комбинация тоже допустима и тогда пресета просто нет.
    """
    rows = {row.node: row.flags
            for row in RolePermission.objects.filter(role_id=role_id)}
    return [
        {"node": node, "flags": sorted(flags), "preset": depth.preset_of(flags)}
        for node, flags in sorted(rows.items())
    ]


def set_permissions(role_id: int, items: list[dict]) -> None:
    """Замена набора ЦЕЛИКОМ (спека §4.2).

    Частичная правка означала бы, что «забыли прислать узел» тихо равносильно
    «оставить как было». При замене целиком отсутствие узла означает
    «наследовать от предка» — а явный пустой набор флагов, наоборот, запрет:
    это две разные вещи, и различать их обязан сам вызывающий.

    Узел, которого нет в реестре, отвергается: право на несуществующую функцию
    никогда ни на что не влияет, и завести его молча — значит выдать роль,
    которая не работает.
    """
    known = registry.paths()
    unknown = sorted({i["node"] for i in items if i["node"] not in known})
    if unknown:
        raise UnknownModule(f"нет таких функций: {unknown}")

    rows = []
    for item in items:
        flags = (depth.flags_of(item["preset"]) if item.get("preset")
                 else frozenset(item.get("flags") or ()))
        bad = sorted(flags - set(depth.FLAGS))
        if bad:
            raise UnknownModule(f"нет таких признаков глубины: {bad}")
        # Признак, не применимый к узлу, отвергается, а не отбрасывается молча:
        # тихо срезав его, мы сохранили бы роль, отличающуюся от заданной, и
        # человек считал бы, что выдал право, которого на самом деле нет.
        applicable = registry.applicable_flags(item["node"])
        extra = sorted(flags - applicable)
        if extra:
            raise DepthNotApplicable(
                f"к функции {item['node']!r} неприменимы признаки: {extra}; "
                f"допустимы: {sorted(applicable) or 'нет ни одного'}"
            )
        row = RolePermission(role_id=role_id, node=item["node"])
        row.set_flags(flags)
        rows.append(row)

    with transaction.atomic():
        RolePermission.objects.filter(role_id=role_id).delete()
        RolePermission.objects.bulk_create(rows)
