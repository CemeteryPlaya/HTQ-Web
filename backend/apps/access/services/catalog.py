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

from apps.access.models import Level, Role, RoleModulePermission
from apps.access.services.errors import (
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
    return [
        {"module": row["module"], "level": row["level"]}
        for row in (RoleModulePermission.objects
                    .filter(role_id=role_id)
                    .order_by("module")
                    .values("module", "level"))
    ]


def set_permissions(role_id: int, items: list[dict]) -> None:
    """Замена набора ЦЕЛИКОМ: отсутствующий модуль становится ``none``.

    Частичная правка означала бы, что «забыли прислать модуль» тихо
    равносильно «оставить как было» (спека §4.2). Проверка и запись — одной
    транзакцией: отказ на середине набора не должен оставить роль без прав.
    """
    from apps.core.models import KNOWN_SERVICES

    unknown = sorted({i["module"] for i in items if i["module"] not in KNOWN_SERVICES})
    if unknown:
        raise UnknownModule(f"нет таких модулей: {unknown}")

    with transaction.atomic():
        RoleModulePermission.objects.filter(role_id=role_id).delete()
        RoleModulePermission.objects.bulk_create([
            RoleModulePermission(role_id=role_id, module=i["module"], level=i["level"])
            for i in items if i["level"] != Level.NONE
        ])
