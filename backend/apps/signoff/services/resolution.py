"""Кому адресовать этап — с флагами маршрута (мастер-план БЗО, B1.2 / D-21).

Движок без флагов разворачивает исполнителей всех этапов на запуске
(``engine._resolve_stages``) и отказывает в запуске, если кого-то нет. Здесь —
то, что добавляют флаги:

- **ленивое разрешение** (``lazy_resolution``, ТЗ §16.1 п.2): этап получает
  исполнителей, когда становится активным, по СНИМКУ своей настройки
  (``ApprovalProcessStage.role_ids``/``user_ids``/``approver_key``), и с
  учётом временных исполнителей на этот день. Нет исполнителя у группы — это
  не отказ, а «Нет исполнителя» (ТЗ §16.1 п.5): ``missing``;
- **запрет самосогласования** (``forbid_self_approval``, BR-061): автор
  исключается из своей группы; не осталось никого — группа уходит держателям
  должности эскалации (ГД); автор и есть ГД — группа пропускается
  (``skipped``), и об этом уведомляют (D-22).

Группа — ключ кворума, как в движке: HR-должность, у видов без должностей —
``None``. Ошибки НАСТРОЙКИ (этап без должностей, без названных сотрудников)
остаются отказом и здесь: «Нет исполнителя» — про людей, а не про пустой
маршрут.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from apps.hr import interface as hr
from apps.users import interface as users

from apps.signoff.models import ApproverKind
from apps.signoff.services import registry

#: Флаги маршрута и их значения «выключено» — ровно столбцы ``ApprovalRoute``.
ROUTE_FLAG_DEFAULTS: dict = {
    "forbid_self_approval": False,
    "reject_comment_min": 0,
    "lazy_resolution": False,
    "no_executor_notify_position_ids": [],
    "escalation_position_id": None,
    "self_skip_notify_position_ids": [],
}


def route_flags_of(route) -> dict:
    """Снимок флагов маршрута — то, что ляжет в ``ApprovalProcess.route_flags``."""
    return {key: getattr(route, key) for key in ROUTE_FLAG_DEFAULTS}


def flags_of(process) -> dict:
    """Флаги идущего процесса; у процессов до флагов — все выключены."""
    return {**ROUTE_FLAG_DEFAULTS, **(process.route_flags or {})}


class StageNotConfigured(Exception):
    """Этап настроен так, что исполнителей у него не бывает в принципе."""


@dataclass
class Resolution:
    groups: dict[int | None, list[int]] = field(default_factory=dict)
    missing: list[int | None] = field(default_factory=list)
    skipped: list[int | None] = field(default_factory=list)
    escalated: list[int | None] = field(default_factory=list)


def resolve_process_stage(stage, *, initiator_id: int | None, subject_type: str,
                          subject_id: str, flags: dict,
                          exclude_positions=()) -> Resolution:
    """Исполнители этапа идущего процесса — по снимку этапа, на сегодня.

    ``exclude_positions`` — предсогласованные должности (D-26): у них задач
    нет и «Нет исполнителя» они не дают."""
    kind = stage.approver_kind
    result = Resolution()

    if kind == ApproverKind.INITIATOR:
        if initiator_id is None:
            raise StageNotConfigured(
                f"Этап «{stage.name}» подписывает инициатор, но согласование "
                f"запущено без инициатора")
        raw = {None: [initiator_id]}
    elif kind == ApproverKind.USERS:
        ids = [int(uid) for uid in dict.fromkeys(stage.user_ids or [])]
        if not ids:
            raise StageNotConfigured(f"На этапе «{stage.name}» не назван ни один согласующий")
        raw = {None: ids}
    elif kind == ApproverKind.SUBJECT:
        raw = {None: list(registry.approvers_for(subject_type, subject_id,
                                                 stage.approver_key))}
    else:
        position_ids = [int(pid) for pid in (stage.role_ids or [])]
        if not position_ids:
            raise StageNotConfigured(f"На этапе «{stage.name}» не назначена ни одна должность")
        excluded = {int(pid) for pid in exclude_positions}
        position_ids = [pid for pid in position_ids if pid not in excluded]
        if not position_ids:
            return result
        resolved = hr.resolve_position_users(position_ids)
        raw = {position_id: list(dict.fromkeys(resolved.get(position_id) or []))
               for position_id in position_ids}

    if kind != ApproverKind.POSITION:
        # Должности HR уже отфильтровал по активным учёткам; у остальных видов
        # список — как назвали маршрут или объект, его проверяем здесь.
        active = _active([uid for ids in raw.values() for uid in ids])
        raw = {key: [uid for uid in ids if uid in active] for key, ids in raw.items()}

    for key, ids in raw.items():
        if ids:
            result.groups[key] = ids
        else:
            result.missing.append(key)

    if kind != ApproverKind.INITIATOR:
        apply_self_approval(result, initiator_id=initiator_id, flags=flags)
    return result


def apply_self_approval(result: Resolution, *, initiator_id: int | None,
                        flags: dict) -> None:
    """BR-061 поверх разрешённых групп (на месте). Без флага — ничего.

    Временные исполнители должности уже в группе (``hr.resolve_position_users``),
    поэтому «держатель или его заместитель» получается сам собой: из группы
    уходит только автор.
    """
    if not flags.get("forbid_self_approval") or initiator_id is None:
        return
    escalation = flags.get("escalation_position_id")
    for key in list(result.groups):
        ids = result.groups[key]
        if initiator_id not in ids:
            continue
        rest = [uid for uid in ids if uid != initiator_id]
        if rest:
            result.groups[key] = rest
            continue
        heads = []
        if escalation:
            heads = [uid for uid in hr.resolve_position_users([escalation]).get(escalation, [])
                     if uid != initiator_id]
        if heads:
            result.groups[key] = heads
            result.escalated.append(key)
        else:
            del result.groups[key]
            result.skipped.append(key)


def position_user_ids(position_ids) -> list[int]:
    """Держатели (и временные исполнители) должностей — для уведомлений."""
    ids = [int(pid) for pid in (position_ids or [])]
    if not ids:
        return []
    resolved = hr.resolve_position_users(ids)
    return list(dict.fromkeys(uid for pid in ids for uid in resolved.get(pid, [])))


def _active(user_ids) -> set[int]:
    ids = list(dict.fromkeys(user_ids))
    if not ids:
        return set()
    return {row["id"] for row in users.get_users_brief(ids) if row.get("is_active")}
