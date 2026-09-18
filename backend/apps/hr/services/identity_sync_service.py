"""Синк аккаунт → копия идентичности в карточке (спека §8).

Восстанавливает то, что потерялось при обратной миграции на Django: в
FastAPI-поколении копию поддерживал воркер ``user_avatar_sync``, а в монолите
достаточно вызова в процессе — событийная шина не нужна.

Направление здесь ровно одно. Обратное (копия → аккаунт) идёт заявкой через
``identity_request_service``: запись в чужой аккаунт всегда санкционирует
человек, и другого пути в ``apps.users`` из hr не существует.
"""
from __future__ import annotations

from django.db import transaction

from apps.hr.models import Employee, IdentityChangeRequest
from apps.hr.services.identity_fields import FIELD_MAP, SYNCABLE, differs
from apps.users import interface as users_interface
from htqweb.fallback import fallback


def account_snapshot(user_id: int) -> dict | None:
    """Профиль владельца, переведённый в термины полей Employee.

    ``None`` — аккаунта нет (удалён) или аппка users выключена. Перевод делаем
    здесь, а не у вызывающих: FIELD_MAP — единственное место, где живёт
    соответствие имён, и раскладывать его по сервисам значило бы завести
    второй источник правды.
    """
    profile = users_interface.get_user_profile_for_hr(user_id)
    if profile is None:
        return None
    return {
        employee_field: profile.get(account_field, "")
        for employee_field, account_field in FIELD_MAP.items()
    }


def diff_against_account(employee: Employee, snapshot: dict) -> list[str]:
    """Поля копии, разошедшиеся с аккаунтом. ``email`` не участвует."""
    return [
        field for field in SYNCABLE
        if differs(field, getattr(employee, field), snapshot.get(field))
    ]


@transaction.atomic
def sync_employee(employee_id: int) -> list[str]:
    """Перезаписать копию значениями аккаунта. Возвращает изменённые поля.

    Ничего не спрашивает и никого не уведомляет: владелец идентичности —
    аккаунт, и приведение копии к нему никого не затрагивает.
    """
    employee = Employee.objects.select_for_update().filter(pk=employee_id).first()
    if employee is None or not employee.user_id:
        return []

    snapshot = account_snapshot(employee.user_id)
    if snapshot is None:
        # Аккаунт удалён или users выключен: копию не трогаем — это штатная
        # деградация, а не ошибка синка.
        return fallback(
            "hr.identity_sync.account_missing", [],
            reason="аккаунт сотрудника недоступен", expected=True,
            employee_id=employee_id, user_id=employee.user_id,
        )

    changed = diff_against_account(employee, snapshot)
    if not changed:
        return []

    for field in changed:
        setattr(employee, field, snapshot.get(field) or None)
    employee.save(update_fields=[*changed, "updated_at"])
    return changed


def reconcile_employee(employee_id: int) -> IdentityChangeRequest | None:
    """Ночной проход: расхождение = кто-то писал в копию мимо API.

    Порядок «сначала заявка, потом перезапись» обязателен: он гарантирует, что
    найденное кадровое значение переживёт падение воркера между шагами. Молча
    затирать нельзя — иначе никто не узнает ни о потерянном значении, ни о
    существовании пути записи в обход правила.
    """
    from apps.hr.services import identity_request_service

    employee = Employee.objects.filter(pk=employee_id).first()
    if employee is None or not employee.user_id:
        return None

    snapshot = account_snapshot(employee.user_id)
    if snapshot is None:
        return fallback(
            "hr.identity_sync.account_missing", None,
            reason="аккаунт сотрудника недоступен", expected=True,
            employee_id=employee_id, user_id=employee.user_id,
        )

    drifted = diff_against_account(employee, snapshot)
    if not drifted:
        return None

    # expected=False намеренно: это не предусмотренная деградация, а сигнал,
    # что какой-то путь записи работает мимо правила «копия только из синка».
    fallback(
        "hr.identity_sync.copy_drift", None,
        reason="копия идентичности разошлась с аккаунтом мимо API",
        expected=False, employee_id=employee_id, fields=",".join(drifted),
    )

    _, request = identity_request_service.capture(
        employee,
        {field: getattr(employee, field) for field in drifted},
        actor_id=None,
        source=IdentityChangeRequest.Source.NIGHTLY,
    )
    sync_employee(employee_id)
    return request
