"""Должность как пара «компания + должность» (БЗО, B8.1).

До B8.1 этап маршрута стоял только на должностях своей компании, и движок
адресовал должность голым ``position_id``. Директора компаний группы — в
штате холдинга, у дочерних их нет (Q-B15, Q-E02), поэтому этап маршрута
дочерней вправе стоять на должности ВЫШЕСТОЯЩЕЙ компании. Должности у
компаний свои, и id повторяются по схемам, — значит, должность адресуется
парой ``PositionRef(company, position_id)``, где ``company=""`` — своя
компания (так хранятся все должности, заведённые до B8.1).

Задачи, процессы и документы при этом остаются в схеме дочерней: учётки
пользователей общие на платформу, и задача на директора холдинга в схеме
дочерней — обычная задача. В чужую схему движок заходит ровно с двумя
вопросами: кто сейчас держит должность (``resolve_users``) и как она
называется (``briefs``).

Допустимые компании — своя и действующие вышестоящие
(``companies.interface.ancestor_slugs``). Недоступная компания (архив, нет
схемы, выключен ``hr``, перестала быть вышестоящей) — не подмена, а явная
причина ``CompanyUnavailable``: движок на запуске без ленивого разрешения
отказывает, с ним — ставит этапу «Нет исполнителя». Подменой (через
``htqweb.fallback``) бывает только ПОДПИСЬ должности: карточка не должна
падать из-за того, что холдинг на миг недоступен.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import NamedTuple

from apps.companies import interface as companies
from apps.core.services import ServiceDisabled
from apps.hr import interface as hr
from htqweb.fallback import fallback
from htqweb.tenancy import current_company_or_none
from htqweb.tenancy.db import use_company


class PositionRef(NamedTuple):
    """Должность в штате компании ``company`` (``""`` — своей)."""

    company: str
    position_id: int

    def as_dict(self) -> dict:
        return {"company": self.company, "position_id": self.position_id}


class PositionRefError(ValueError):
    """Ссылку на должность нельзя записать в маршрут: компания не своя и не
    вышестоящая или должности в ней нет. Текст — для человека."""


class CompanyUnavailable(Exception):
    """В компанию должности сейчас не войти. ``reason`` — для человека."""

    def __init__(self, company: str, reason: str):
        self.company = company
        self.reason = reason
        super().__init__(reason)


# ── Разбор и запись ─────────────────────────────────────────────────────

def normalize(company: str | None) -> str:
    """Своя компания — пустая строка, в каком бы виде её ни прислали: клиент
    вправе назвать её слагом, а храниться она обязана одинаково, иначе одна
    должность разошлась бы на две по уникальности и кворуму."""
    company = (company or "").strip()
    if company and company == current_company_or_none():
        return ""
    return company


def parse(item) -> PositionRef:
    """Из того, что хранится и приходит: число — своя должность (так её
    передают все вызывающие до B8.1), ``{company, position_id}`` — пара."""
    if isinstance(item, PositionRef):
        return PositionRef(normalize(item.company), int(item.position_id))
    if isinstance(item, dict):
        return PositionRef(normalize(item.get("company")), int(item["position_id"]))
    return PositionRef("", int(item))


def parse_many(items) -> list[PositionRef]:
    """Список пар без дублей, порядок сохраняется."""
    return list(dict.fromkeys(parse(item) for item in items or []))


def dump_many(refs) -> list[dict]:
    return [ref.as_dict() for ref in refs]


def route_stage_refs(stage) -> list[PositionRef]:
    """Должности этапа маршрута (``ApprovalRouteStageRole``)."""
    return [PositionRef(row.position_company or "", int(row.position_id))
            for row in stage.roles.all()]


def process_stage_refs(stage) -> list[PositionRef]:
    """Должности этапа процесса — снимок ``role_refs``; у этапов, заведённых
    до B8.1, — ``role_ids`` как должности своей компании."""
    if stage.role_refs:
        return parse_many(stage.role_refs)
    return [PositionRef("", int(position_id)) for position_id in (stage.role_ids or [])]


def task_keys(task) -> list[PositionRef | None]:
    """Группы кворума, которые закрывает задача: её должность и
    ``also_positions`` (один человек на двух должностях этапа). Задача без
    должности (инициатор, люди поимённо, назначенные объектом, задачи до
    0007) — одна группа ``None``, как и раньше."""
    if task.position_id is None:
        return [None]
    keys = [PositionRef(task.position_company or "", int(task.position_id))]
    keys.extend(parse(item) for item in task.also_positions or [])
    return list(dict.fromkeys(keys))


# ── Чужая компания ──────────────────────────────────────────────────────

def allowed_companies() -> list[str]:
    """Чьи должности может назвать маршрут текущей компании: своя (``""``)
    и действующие вышестоящие, ближайшая первой."""
    current = current_company_or_none()
    return ["", *(companies.ancestor_slugs(current) if current else [])]


@contextmanager
def in_company(company: str):
    """Блок в схеме компании должности; своя (``""``) — без переключения.

    ``use_company`` восстанавливает ПРЕЖНЮЮ компанию, поэтому заход в схему
    холдинга посреди транзакции дочерней возвращает соединение обратно в
    дочернюю."""
    if not company:
        yield
        return
    with use_company(company):
        yield


def ensure_available(company: str) -> None:
    """Войти в компанию должности можно? Нет — ``CompanyUnavailable`` с
    причиной. Своя компания доступна всегда — по ней отвечает она сама."""
    if not company:
        return
    row = companies.get_company(company)
    if row is None:
        raise CompanyUnavailable(company, f"компания «{company}» не найдена")
    if not row["is_active"]:
        raise CompanyUnavailable(company, f"компания «{row['name']}» в архиве")
    if company not in allowed_companies():
        raise CompanyUnavailable(
            company, f"компания «{row['name']}» больше не вышестоящая — "
                     f"исправьте маршрут")
    if not companies.schema_exists(company):
        raise CompanyUnavailable(company, f"у компании «{row['name']}» нет схемы")


def _by_company(refs) -> dict[str, list[int]]:
    grouped: dict[str, list[int]] = {}
    for ref in refs:
        grouped.setdefault(ref.company, [])
        if ref.position_id not in grouped[ref.company]:
            grouped[ref.company].append(ref.position_id)
    return grouped


def resolve_users(refs, *, on_date=None) -> dict[PositionRef, list[int]]:
    """Держатели и временные исполнители должностей — ``{ref: user_ids}``.

    Один заход в схему на компанию: временные исполнители должности холдинга
    живут в схеме холдинга, там их и находит ``hr.resolve_position_users``.
    Недоступная чужая компания — ``CompanyUnavailable``: отказ это или «Нет
    исполнителя», решает движок. Выключенный ``hr`` своей компании, как и до
    B8.1, — ``ServiceDisabled``.
    """
    out: dict[PositionRef, list[int]] = {}
    for company, ids in _by_company(refs).items():
        ensure_available(company)
        try:
            with in_company(company):
                resolved = hr.resolve_position_users(ids, on_date=on_date)
        except ServiceDisabled as exc:
            if not company:
                raise
            raise CompanyUnavailable(company, "кадровый модуль выключен") from exc
        for position_id in ids:
            out[PositionRef(company, position_id)] = list(
                dict.fromkeys(resolved.get(position_id) or []))
    return out


def company_name(company: str) -> str | None:
    """Название компании должности; у своей — ``None`` (подпись без неё)."""
    if not company:
        return None
    row = companies.get_company(company)
    return row["name"] if row else company


def briefs(refs) -> dict[PositionRef, dict]:
    """``{ref: {position_id, company, company_name, title, department_name,
    is_active, label}}`` — подписи должностей для карточек и редактора.

    Оформление, а не решение: недоступная чужая компания даёт подпись
    «Должность #id» через ``fallback`` (``expected=True`` — предусмотренная
    деградация), а не роняет карточку процесса или маршрута.
    """
    out: dict[PositionRef, dict] = {}
    for company, ids in _by_company(refs).items():
        rows: dict[int, dict] = {}
        try:
            ensure_available(company)
            with in_company(company):
                rows = {row["id"]: row for row in hr.get_positions_brief(ids)}
        except (CompanyUnavailable, ServiceDisabled) as exc:
            if not company:
                raise
            rows = fallback("signoff.positions.brief_unavailable", {},
                            reason="должности вышестоящей компании недоступны",
                            exc=exc, expected=True, company=company)
        name = company_name(company)
        for position_id in ids:
            row = rows.get(position_id) or {}
            title = row.get("title") or f"Должность #{position_id}"
            out[PositionRef(company, position_id)] = {
                "position_id": position_id,
                "company": company,
                "company_name": name,
                "title": title,
                "department_name": row.get("department_name"),
                "is_active": bool(row.get("is_active", False)),
                "label": f"{title} · {name}" if name else title,
            }
    return out


def check_refs(refs) -> list[PositionRef]:
    """Проверить должности перед записью в маршрут — нормализованный список
    без дублей или ``PositionRefError``.

    Компания — своя или действующая вышестоящая (решение 02.10: «из своей
    компании и выше по дереву»); должность в ней существует. Проверяется на
    настройке, а не на запуске: опечатка иначе дожила бы до отправки
    документа и всплыла у человека, к маршруту отношения не имеющего.
    """
    refs = parse_many(refs)
    allowed = set(allowed_companies())
    foreign = sorted({ref.company for ref in refs if ref.company not in allowed})
    if foreign:
        raise PositionRefError(
            "Должность можно взять только из своей компании и вышестоящих: "
            + ", ".join(f"«{company}»" for company in foreign) + " — не вышестоящая")
    for company, ids in _by_company(refs).items():
        try:
            ensure_available(company)
            with in_company(company):
                known = {row["id"] for row in hr.get_positions_brief(ids)}
        except CompanyUnavailable as exc:
            raise PositionRefError(f"Должности не проверить: {exc.reason}") from exc
        unknown = [position_id for position_id in ids if position_id not in known]
        if unknown:
            where = f" в компании «{company_name(company)}»" if company else ""
            raise PositionRefError(
                f"Не найдены должности{where}: " + ", ".join(map(str, unknown)))
    return refs


def list_positions(company: str) -> list[dict]:
    """Справочник должностей компании для редактора маршрута — своей или
    вышестоящей. Другая компания — ``PositionRefError``."""
    company = normalize(company)
    if company not in allowed_companies():
        raise PositionRefError("Должности этой компании маршруту недоступны")
    try:
        ensure_available(company)
    except CompanyUnavailable as exc:
        raise PositionRefError(exc.reason) from exc
    with in_company(company):
        return hr.list_positions_brief()
