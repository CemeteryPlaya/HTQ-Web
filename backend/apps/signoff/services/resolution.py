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

Группа — ключ кворума, как в движке: должность парой «компания + должность»
(``positions.PositionRef``, БЗО B8.1: этап дочерней может стоять на
должности холдинга), у видов без должностей — ``None``. Ошибки НАСТРОЙКИ
(этап без должностей, без названных сотрудников) остаются отказом и здесь:
«Нет исполнителя» — про людей, а не про пустой маршрут. Недоступная компания
должности (архив, нет схемы, выключен ``hr``) — тоже «Нет исполнителя», с
причиной в ``unavailable``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from apps.users import interface as users

from apps.signoff.models import ApproverKind
from apps.signoff.services import positions, registry
from apps.signoff.services.positions import PositionRef
from htqweb.fallback import fallback

#: Флаги маршрута и их значения «выключено» — ровно столбцы ``ApprovalRoute``.
#: ``allow_direct_decisions`` (B8.1) сюда НЕ входит намеренно: решение «прямо
#: из холдинга» читается из маршрута в момент решения, а не из снимка.
ROUTE_FLAG_DEFAULTS: dict = {
    "forbid_self_approval": False,
    "reject_comment_min": 0,
    "lazy_resolution": False,
    "skip_unmatched_groups": False,
    "no_executor_notify_position_ids": [],
    "escalation_position_id": None,
    "self_skip_notify_position_ids": [],
    # B8.1: должности вышестоящих компаний для тех же ролей.
    "escalation_position_company": "",
    "no_executor_notify_foreign": [],
    "self_skip_notify_foreign": [],
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
    groups: dict[PositionRef | None, list[int]] = field(default_factory=dict)
    missing: list[PositionRef | None] = field(default_factory=list)
    skipped: list[PositionRef | None] = field(default_factory=list)
    escalated: list[PositionRef | None] = field(default_factory=list)
    # Компании должностей, в которые сейчас не войти: ``{company: причина}``.
    unavailable: dict[str, str] = field(default_factory=dict)


def resolve_refs(refs, *, strict: bool) -> tuple[dict[PositionRef, list[int]], dict[str, str]]:
    """Держатели должностей по компаниям — ``(resolved, unavailable)``.

    ``strict`` — недоступная компания роняет вызов ``CompanyUnavailable``
    (запуск без ленивого разрешения); иначе её должности остаются без
    держателей, а причина — в ``unavailable`` (ленивое разрешение, «Нет
    исполнителя»)."""
    by_company: dict[str, list[PositionRef]] = {}
    for ref in refs:
        by_company.setdefault(ref.company, []).append(ref)
    resolved: dict[PositionRef, list[int]] = {}
    unavailable: dict[str, str] = {}
    for company, group in by_company.items():
        try:
            resolved.update(positions.resolve_users(group))
        except positions.CompanyUnavailable as exc:
            if strict:
                raise
            unavailable[company] = exc.reason
    return resolved, unavailable


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
        refs = positions.process_stage_refs(stage)
        if not refs:
            raise StageNotConfigured(f"На этапе «{stage.name}» не назначена ни одна должность")
        excluded = set(positions.parse_many(exclude_positions))
        refs = [ref for ref in refs if ref not in excluded]
        if not refs:
            return result
        resolved, result.unavailable = resolve_refs(refs, strict=False)
        raw = {ref: list(dict.fromkeys(resolved.get(ref) or [])) for ref in refs}

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


def escalation_ref(flags: dict) -> PositionRef | None:
    """Должность эскалации снимка флагов — своя или вышестоящей компании (B8.1)."""
    position_id = flags.get("escalation_position_id")
    if not position_id:
        return None
    return PositionRef(positions.normalize(flags.get("escalation_position_company")),
                       int(position_id))


def apply_self_approval(result: Resolution, *, initiator_id: int | None,
                        flags: dict) -> None:
    """BR-061 поверх разрешённых групп (на месте). Без флага — ничего.

    Временные исполнители должности уже в группе (``hr.resolve_position_users``),
    поэтому «держатель или его заместитель» получается сам собой: из группы
    уходит только автор.

    Должность эскалации может быть в штате холдинга (B8.1). Холдинг сейчас
    недоступен — группа не пропускается (пропуск без решения согласовал бы
    документ за ГД), а становится «Нет исполнителя» с причиной.
    """
    if not flags.get("forbid_self_approval") or initiator_id is None:
        return
    escalation = escalation_ref(flags)
    for key in list(result.groups):
        ids = result.groups[key]
        if initiator_id not in ids:
            continue
        rest = [uid for uid in ids if uid != initiator_id]
        if rest:
            result.groups[key] = rest
            continue
        heads = []
        if escalation is not None:
            try:
                heads = [uid for uid in positions.resolve_users([escalation]).get(escalation, [])
                         if uid != initiator_id]
            except positions.CompanyUnavailable as exc:
                del result.groups[key]
                result.missing.append(key)
                result.unavailable[exc.company] = exc.reason
                continue
        if heads:
            result.groups[key] = heads
            result.escalated.append(key)
        else:
            del result.groups[key]
            result.skipped.append(key)


def notify_refs(flags: dict, own_key: str, foreign_key: str) -> list[PositionRef]:
    """Получатели уведомления из снимка флагов: должности своей компании
    (``own_key``) и вышестоящих (``foreign_key``, B8.1)."""
    refs = [PositionRef("", int(pid)) for pid in (flags.get(own_key) or [])]
    refs.extend(positions.parse_many(flags.get(foreign_key) or []))
    return list(dict.fromkeys(refs))


def position_user_ids(refs) -> list[int]:
    """Держатели (и временные исполнители) должностей — для уведомлений.

    ``refs`` — пары или голые id своей компании. Уведомление — не решение:
    недоступная вышестоящая компания оставляет своих держателей без него,
    и это видно в логе (``fallback``, ``expected=True``), а не роняет
    согласование.
    """
    refs = positions.parse_many(refs)
    if not refs:
        return []
    resolved, unavailable = resolve_refs(refs, strict=False)
    for company, reason in unavailable.items():
        fallback("signoff.resolution.notify_company_unavailable", None,
                 reason=f"уведомление не дойдёт до должностей компании: {reason}",
                 expected=True, company=company)
    return list(dict.fromkeys(uid for ref in refs for uid in resolved.get(ref, [])))


def _active(user_ids) -> set[int]:
    ids = list(dict.fromkeys(user_ids))
    if not ids:
        return set()
    return {row["id"] for row in users.get_users_brief(ids) if row.get("is_active")}
