"""Ссылки автоматизаций на удалённое (спецификация логики §10, решение L-01).

Своё поле доски, вариант списка и шаблон чек-листа администратор доски
правит сам — удалить их, пока на них ссылается автоматизация этой доски,
нельзя (409 ``automation_ref_in_use`` с названиями). Общую метку компании,
сотрудника, отдел и проект удаляют другие люди и другие разделы — удаление
идёт, а затронутые автоматизации ломаются: выключаются, получают
``broken_reason`` и уведомляют администраторов доски и автора. Движок ничего
не вычисляет по отсутствующей ссылке молча: ``RefMissing`` при выполнении —
та же поломка.
"""

from __future__ import annotations

from apps.companies import interface as companies
from apps.hr import interface as hr
from htqweb.errors import DomainError
from htqweb.tenancy.context import current_company_or_none

from ...models import AutomationRule, AutomationRun, AutomationRunStatus, BoardKind, Project
from .. import task_notify
from . import catalog


class RefMissing(DomainError):
    """То, на что ссылается автоматизация, удалили."""

    def __init__(self, message: str):
        super().__init__("automation_ref_missing", message, status=422)


# ── что использует ─────────────────────────────────────────────────────

def _board_rules(board_kind: str, board_id: int):
    return AutomationRule.objects.filter(board_kind=board_kind, board_id=board_id).order_by(
        "position", "id")


def _uses_option(refs, field_id: int, option_id: str) -> bool:
    return any(str(getattr(spec, "value", None)) == str(option_id)
               for _use, spec in refs.fields.get(field_id, []))


def using(board_kind: str, board_id: int, *, field_id: int | None = None,
          option_id: str | None = None, template_id: str | None = None) -> list[AutomationRule]:
    """Автоматизации доски, которые ссылаются на поле, вариант поля-списка
    или шаблон чек-листа."""
    found = []
    for rule in _board_rules(board_kind, board_id):
        refs = catalog.references(rule)
        if option_id is not None:
            hit = _uses_option(refs, field_id, option_id)
        elif field_id is not None:
            hit = field_id in refs.fields
        else:
            hit = template_id in refs.templates
        if hit:
            found.append(rule)
    return found


def _title(rule: AutomationRule) -> str:
    return f"«{rule.name}»" if rule.name else f"№{rule.pk}"


def ensure_unused(board_kind: str, board_id: int, what: str, **ref) -> None:
    """Удаление своего поля, варианта или шаблона доски, пока на него ссылается
    автоматизация этой доски, — 409 с названиями (решение L-01)."""
    rules = using(board_kind, board_id, **ref)
    if rules:
        names = ", ".join(_title(rule) for rule in rules[:5])
        more = f" и ещё {len(rules) - 5}" if len(rules) > 5 else ""
        raise DomainError(
            "automation_ref_in_use",
            f"{what} используется в автоматизациях доски: {names}{more} — сначала поправьте их",
            status=409, details={"automation_ids": [rule.pk for rule in rules]})


# ── поломка ─────────────────────────────────────────────────────────────

def admins(rule: AutomationRule) -> set[int]:
    """Кто узнаёт о поломке: администраторы доски (глава отдела или владелец
    проекта задач) и автор автоматизации."""
    ids = {rule.created_by, rule.updated_by}
    if rule.board_kind == BoardKind.DEPARTMENT:
        try:
            ids.update(hr.department_manager_user_ids([rule.board_id]).values())
        except Exception:  # noqa: BLE001 — кадры выключены: остаётся автор
            pass
    else:
        ids.add(Project.objects.filter(pk=rule.board_id).values_list("owner_id", flat=True).first())
    return {uid for uid in ids if uid}


def mark_broken(rule: AutomationRule, reason: str) -> None:
    """Выключить автоматизацию с причиной, записать в журнал и уведомить."""
    reason = reason[:500]
    updated = AutomationRule.objects.filter(pk=rule.pk, broken_reason="").update(
        enabled=False, broken_reason=reason)
    rule.enabled, rule.broken_reason = False, reason
    if not updated:
        return  # уже сломана — второе уведомление ни к чему
    AutomationRun.objects.create(
        rule=rule, board_kind=rule.board_kind, board_id=rule.board_id,
        rule_name=rule.name[:200], status=AutomationRunStatus.CHANGED,
        details={"broken": reason})
    task_notify.automation_broken(
        rule.board_kind, rule.board_id, admins(rule),
        f"Автоматизация {_title(rule)} выключена: {reason}")


def label_deleted(label_id: int, name: str) -> int:
    """Метку компании удаляют — автоматизации всех досок, где она упомянута,
    ломаются. Число сломанных."""
    count = 0
    for rule in AutomationRule.objects.filter(broken_reason=""):
        if label_id in catalog.references(rule).labels:
            mark_broken(rule, f"удалена метка «{name}»")
            count += 1
    return count


def board_gone(board_kind: str, board_id: int, reason: str) -> int:
    """Отдела или проекта доски больше нет — её автоматизации сломаны."""
    rules = list(_board_rules(board_kind, board_id).filter(broken_reason=""))
    for rule in rules:
        mark_broken(rule, reason)
    return len(rules)


def sweep() -> int:
    """Ночная сверка (уборка журнала, раз в сутки): сотрудники, которые больше
    не работают в компании, и доски, чьих отделов и проектов нет. Число
    сломанных."""
    slug = current_company_or_none()
    members = set(companies.active_member_ids(slug)) if slug else None
    departments: dict[int, bool] = {}
    count = 0
    for rule in AutomationRule.objects.filter(broken_reason=""):
        if rule.board_kind == BoardKind.DEPARTMENT:
            if rule.board_id not in departments:
                departments[rule.board_id] = hr.get_department_brief(rule.board_id) is not None
            if not departments[rule.board_id]:
                mark_broken(rule, "отдела доски больше нет")
                count += 1
                continue
        elif not Project.objects.filter(pk=rule.board_id).exists():
            mark_broken(rule, "проекта доски больше нет")
            count += 1
            continue
        if members is not None and (gone := catalog.references(rule).users - members):
            people = ", ".join(task_notify.person_name(uid) for uid in sorted(gone))
            mark_broken(rule, f"больше не работает в компании: {people}")
            count += 1
    return count
