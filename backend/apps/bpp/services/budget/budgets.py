"""Бюджет проекта: черновик, утверждение, корректировка, закрытие (ТЗ §06, §15.1).

Утверждение и корректировка — прямое действие ФД без маршрута ``signoff``
(D-07): ФД и ведёт бюджет, и утверждает его. Права — узлы ``bpp.budgets``
(просмотр, создание, правка, удаление черновика) и ``bpp.budgets.approve``
(утвердить, корректировать, закрыть, открыть).

Каждое изменение — проверка ``version`` формы (E-CON-01, D-29), новая
версия записи и строка журнала (``audit.record``) в той же транзакции.
"""

from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.bpp.models import (
    Budget,
    BudgetLine,
    BudgetStatus,
    BudgetVersion,
    BudgetVersionStatus,
    PurchaseRequest,
    RequestStatus,
)
from apps.bpp.services.actor import Actor
from apps.bpp.services.core import audit
from apps.bpp.services.core.errors import check_version
from apps.bpp.services.money import fmt, money
from apps.project import interface as projects
from apps.refdata import interface as refdata
from htqweb.errors import DomainError

from . import committed as calc

COMMENT_MIN = 10


# ── права ───────────────────────────────────────────────────────────────

def _deny(action: str, budget: Budget | None = None) -> DomainError:
    what = f"бюджетом {budget.number}" if budget else "бюджетом"
    return DomainError(
        "E-ACC-01",
        f"У вас нет прав {action} {what}. Если это ошибка, обратитесь к администратору.",
        status=403)


def _require(actor: Actor, node: str, flag: str, action: str,
             budget: Budget | None = None) -> None:
    if not actor.can(node, flag):
        raise _deny(action, budget)


def can_view(actor: Actor, budget: Budget) -> bool:
    return actor.can("bpp.budgets", "view") and actor.sees_project(budget.project_id)


def get_visible(actor: Actor, budget_id) -> Budget:
    budget = Budget.objects.filter(pk=budget_id).first()
    if budget is None or not can_view(actor, budget):
        # Чужой бюджет — как несуществующий: ручкой не прощупать чужие id.
        raise DomainError("E-NOT-FOUND", "Бюджет не найден.", status=404)
    return budget


def allowed_actions(actor: Actor, budget: Budget) -> list[str]:
    """Кнопки карточки F-01 (ТЗ §6.6) — по роли и статусу."""
    actions = []
    manage = actor.can("bpp.budgets.approve", "edit")
    draft = _draft_version(budget)
    if budget.status == BudgetStatus.DRAFT:
        if actor.can("bpp.budgets", "edit"):
            actions.append("save")
        if manage:
            actions.append("approve")
        if actor.can("bpp.budgets", "delete"):
            actions.append("delete")
    elif budget.status == BudgetStatus.APPROVED and manage:
        if draft is None:
            actions += ["start_correction", "close"]
        else:
            actions += ["save_correction", "approve_correction", "cancel_correction"]
    elif budget.status == BudgetStatus.CLOSED and manage:
        actions.append("reopen")
    if can_view(actor, budget):
        actions.append("export")
    return actions


# ── проверки строк ──────────────────────────────────────────────────────

def _active_project(project_id) -> dict:
    brief = projects.project_brief([str(project_id)]).get(str(project_id))
    if brief is None:
        raise DomainError("E-NOT-FOUND", "Проект не найден.", status=404,
                          fields=[{"field": "project_id", "message": "Проект не найден"}])
    if brief["status"] != "active":
        raise DomainError(
            "E-PRJ-03", f"Проект {brief['code']} не активен — бюджет ведётся только "
                        f"по активным проектам.",
            fields=[{"field": "project_id", "message": "Проект не активен"}])
    return brief


def _clean_lines(lines: list[dict], *, keep_articles: set[str] = frozenset()) -> list[dict]:
    """Проверить строки формы: статья есть и активна (кроме уже бывших в
    бюджете — архивная статья остаётся в нём, ТЗ §6.5 п.5), без дублей
    (BR-002), лимит ≥ 0."""
    ids = [str(line["article_id"]) for line in lines]
    briefs = refdata.article_brief(ids)
    seen: dict[str, int] = {}
    cleaned = []
    for index, line in enumerate(lines, start=1):
        article_id = str(line["article_id"])
        brief = briefs.get(article_id)
        if brief is None:
            raise DomainError("E-NOT-FOUND", f"Статья в строке {index} не найдена.",
                              fields=[{"field": f"lines[{index - 1}].article_id",
                                       "message": "Статья не найдена"}])
        if not brief["is_active"] and article_id not in keep_articles:
            raise DomainError(
                "E-REF-03", f"Статья «{brief['name']}» в архиве — в бюджет её не добавить.",
                fields=[{"field": f"lines[{index - 1}].article_id",
                         "message": "Статья в архиве"}])
        if article_id in seen:
            raise DomainError(
                "BR-002", f"Статья «{brief['name']}» уже есть в бюджете, строка {seen[article_id]}.",
                fields=[{"field": f"lines[{index - 1}].article_id",
                         "message": "Статья уже есть в бюджете"}])
        seen[article_id] = index
        limit = money(line.get("limit_amount") or 0)
        if limit < 0:
            raise DomainError("E-VAL-01", f"Лимит в строке {index} не может быть отрицательным.",
                              fields=[{"field": f"lines[{index - 1}].limit_amount",
                                       "message": "Лимит ≥ 0"}])
        cleaned.append({"article_id": article_id, "limit_amount": limit,
                        "comment": (line.get("comment") or "")[:255]})
    return cleaned


def _write_lines(version: BudgetVersion, lines: list[dict], actor_id: int) -> None:
    version.lines.all().delete()
    BudgetLine.objects.bulk_create([
        BudgetLine(version=version, article_id=line["article_id"],
                   limit_amount=line["limit_amount"], comment=line["comment"],
                   position=index, created_by=actor_id, updated_by=actor_id)
        for index, line in enumerate(lines, start=1)
    ])


def _snapshot(version: BudgetVersion | None) -> dict[str, str]:
    if version is None:
        return {}
    return {str(line.article_id): str(line.limit_amount) for line in version.lines.all()}


def _touch(budget: Budget, actor_id: int, *fields: str) -> None:
    budget.version += 1
    budget.updated_by = actor_id
    budget.save(update_fields=[*fields, "version", "updated_by", "updated_at"])


def _draft_version(budget: Budget) -> BudgetVersion | None:
    return budget.versions.filter(status=BudgetVersionStatus.DRAFT).first()


def _lock(budget_id) -> Budget:
    budget = Budget.objects.select_for_update().filter(pk=budget_id).first()
    if budget is None:
        raise DomainError("E-NOT-FOUND", "Бюджет не найден.", status=404)
    return budget


def _require_status(budget: Budget, *statuses: str, action: str) -> None:
    if budget.status not in statuses:
        raise DomainError(
            "E-STATE-01",
            f"Бюджет {budget.number} в статусе «{budget.get_status_display()}» — "
            f"{action} сейчас недоступно.",
            status=409)


# ── операции ────────────────────────────────────────────────────────────

@transaction.atomic
def create(actor: Actor, *, project_id, currency: str = "KZT", date_from=None, date_to=None,
           lines: list[dict]) -> Budget:
    _require(actor, "bpp.budgets", "create", "на создание бюджета, работать с")
    project = _active_project(project_id)
    existing = Budget.objects.filter(project_id=project_id).first()
    if existing is not None:
        raise DomainError(
            "BR-001",
            f"У проекта {project['code']} уже есть бюджет {existing.number}. Откройте его и "
            f"выполните корректировку.",
            fields=[{"field": "project_id", "message": "У проекта уже есть бюджет",
                     "budget_id": str(existing.pk)}])
    cleaned = _clean_lines(lines)
    budget = Budget.objects.create(
        project_id=project_id, number=f"БДЖ-{project['code']}", currency=currency or "KZT",
        date_from=date_from, date_to=date_to, created_by=actor.user_id,
        updated_by=actor.user_id)
    version = BudgetVersion.objects.create(budget=budget, version_no=1,
                                           created_by=actor.user_id, updated_by=actor.user_id)
    _write_lines(version, cleaned, actor.user_id)
    audit.record(budget, "created", actor_id=actor.user_id,
                 changes={"project_id": str(project_id), "lines": _snapshot(version)})
    return budget


@transaction.atomic
def update_draft(actor: Actor, budget_id, *, expected_version: int | None, currency=None,
                 date_from=None, date_to=None, lines: list[dict] | None = None) -> Budget:
    budget = _lock(budget_id)
    _require(actor, "bpp.budgets", "edit", "на правку", budget)
    check_version(budget, expected_version)
    _require_status(budget, BudgetStatus.DRAFT, action="правка черновика")
    version = budget.versions.get(version_no=1)
    before = _snapshot(version)
    if lines is not None:
        _write_lines(version, _clean_lines(lines), actor.user_id)
    if currency:
        budget.currency = currency
    budget.date_from, budget.date_to = date_from, date_to
    _touch(budget, actor.user_id, "currency", "date_from", "date_to")
    audit.record(budget, "updated", actor_id=actor.user_id,
                 changes={"lines": {"before": before, "after": _snapshot(version)}})
    return budget


@transaction.atomic
def approve(actor: Actor, budget_id, *, expected_version: int | None) -> Budget:
    budget = _lock(budget_id)
    _require(actor, "bpp.budgets.approve", "edit", "на утверждение", budget)
    check_version(budget, expected_version)
    _require_status(budget, BudgetStatus.DRAFT, action="утверждение")
    version = budget.versions.get(version_no=1)
    total = sum((line.limit_amount for line in version.lines.all()), Decimal("0"))
    if not version.lines.exists() or total <= 0:
        raise DomainError(
            "E-BUD-04", "Утвердить можно бюджет хотя бы с одной строкой и суммой лимитов "
                        "больше нуля.",
            fields=[{"field": "lines", "message": "Σ лимитов должна быть > 0"}])
    now = timezone.now()
    version.status = BudgetVersionStatus.ACTIVE
    version.approved_at, version.approved_by = now, actor.user_id
    version.save(update_fields=["status", "approved_at", "approved_by", "updated_at"])
    budget.status, budget.active_version = BudgetStatus.APPROVED, version
    _touch(budget, actor.user_id, "status", "active_version")
    audit.record(budget, "approved", actor_id=actor.user_id,
                 changes={"version_no": 1, "total": str(total)})
    return budget


@transaction.atomic
def start_correction(actor: Actor, budget_id, *, expected_version: int | None) -> Budget:
    budget = _lock(budget_id)
    _require(actor, "bpp.budgets.approve", "edit", "на корректировку", budget)
    check_version(budget, expected_version)
    _require_status(budget, BudgetStatus.APPROVED, action="корректировка")
    if _draft_version(budget) is not None:
        raise DomainError("E-STATE-01", f"Корректировка бюджета {budget.number} уже открыта.",
                          status=409)
    active = budget.active_version
    draft = BudgetVersion.objects.create(
        budget=budget, version_no=active.version_no + 1, created_by=actor.user_id,
        updated_by=actor.user_id)
    _write_lines(draft, [{"article_id": str(line.article_id), "limit_amount": line.limit_amount,
                          "comment": line.comment} for line in active.lines.all()],
                 actor.user_id)
    _touch(budget, actor.user_id)
    audit.record(budget, "correction_started", actor_id=actor.user_id,
                 changes={"version_no": draft.version_no})
    return budget


def _correction(budget: Budget) -> BudgetVersion:
    draft = _draft_version(budget)
    if draft is None:
        raise DomainError("E-STATE-01",
                          f"У бюджета {budget.number} нет открытой корректировки.", status=409)
    return draft


def _check_kept_articles(budget: Budget, cleaned: list[dict]) -> None:
    """Строки действующей версии из корректировки не удаляются — только
    уменьшается лимит (ТЗ §6.4: «Удалить строку» — только черновик или новая
    строка корректировки)."""
    kept = {line["article_id"] for line in cleaned}
    for line in budget.active_version.lines.all():
        if str(line.article_id) not in kept:
            raise DomainError(
                "E-BUD-05",
                f"Строку статьи «{_name(line.article_id)}» в корректировке удалить нельзя — "
                f"уменьшите её лимит.",
                fields=[{"field": "lines", "message": "Строка действующей версии"}])


def _name(article_id) -> str:
    brief = refdata.article_brief([str(article_id)]).get(str(article_id))
    return brief["name"] if brief else str(article_id)


@transaction.atomic
def save_correction(actor: Actor, budget_id, *, expected_version: int | None,
                    lines: list[dict], comment: str = "") -> Budget:
    budget = _lock(budget_id)
    _require(actor, "bpp.budgets.approve", "edit", "на корректировку", budget)
    check_version(budget, expected_version)
    draft = _correction(budget)
    kept = {str(line.article_id) for line in budget.active_version.lines.all()}
    cleaned = _clean_lines(lines, keep_articles=kept)
    _check_kept_articles(budget, cleaned)
    _write_lines(draft, cleaned, actor.user_id)
    draft.comment = (comment or "")[:1000]
    draft.save(update_fields=["comment", "updated_at"])
    _touch(budget, actor.user_id)
    return budget


@transaction.atomic
def approve_correction(actor: Actor, budget_id, *, expected_version: int | None,
                       comment: str) -> Budget:
    """Утвердить корректировку: BR-004 под блокировкой строк действующей версии.

    Блокировка — те же строки, что берёт ``balance.lock_line``: заявка,
    отправляемая в этот момент, дождётся коммита и перечитает остаток уже
    по новой версии.
    """
    budget = _lock(budget_id)
    _require(actor, "bpp.budgets.approve", "edit", "на корректировку", budget)
    check_version(budget, expected_version)
    draft = _correction(budget)
    comment = (comment or "").strip()
    if len(comment) < COMMENT_MIN:
        raise DomainError(
            "BR-060", f"Комментарий к корректировке — не короче {COMMENT_MIN} символов.",
            fields=[{"field": "comment", "message": f"Минимум {COMMENT_MIN} символов"}])
    active = budget.active_version
    list(BudgetLine.objects.select_for_update().filter(version=active))
    committed = calc.committed_by_article(budget.project_id)
    new_lines = {str(line.article_id): line for line in draft.lines.all()}
    for article_id, used in committed.items():
        line = new_lines.get(article_id)
        limit = line.limit_amount if line else Decimal("0")
        if used > limit:
            raise DomainError(
                "BR-004",
                f"Лимит статьи «{_name(article_id)}» не может быть меньше задействованной "
                f"суммы {fmt(used, budget.currency)}.",
                fields=[{"field": "lines", "message": "Лимит ниже задействованного",
                         "article_id": article_id, "committed": str(used)}])
    before = _snapshot(active)
    now = timezone.now()
    active.status = BudgetVersionStatus.ARCHIVED
    active.save(update_fields=["status", "updated_at"])
    draft.status, draft.comment = BudgetVersionStatus.ACTIVE, comment
    draft.approved_at, draft.approved_by = now, actor.user_id
    draft.save(update_fields=["status", "comment", "approved_at", "approved_by", "updated_at"])
    budget.active_version = draft
    _touch(budget, actor.user_id, "active_version")
    audit.record(budget, "correction_approved", actor_id=actor.user_id, comment=comment,
                 changes={"version_no": draft.version_no,
                          "lines": {"before": before, "after": _snapshot(draft)}})
    return budget


@transaction.atomic
def cancel_correction(actor: Actor, budget_id, *, expected_version: int | None) -> Budget:
    budget = _lock(budget_id)
    _require(actor, "bpp.budgets.approve", "edit", "на корректировку", budget)
    check_version(budget, expected_version)
    draft = _correction(budget)
    version_no = draft.version_no
    draft.delete()
    _touch(budget, actor.user_id)
    audit.record(budget, "correction_cancelled", actor_id=actor.user_id,
                 changes={"version_no": version_no})
    return budget


@transaction.atomic
def close(actor: Actor, budget_id, *, expected_version: int | None, comment: str = "") -> Budget:
    """Закрыть: нет заявок «На согласовании» (ТЗ §15.1). Неоплаченные счета
    добавляются в условие с этапа 3 (B3.2)."""
    budget = _lock(budget_id)
    _require(actor, "bpp.budgets.approve", "edit", "на закрытие", budget)
    check_version(budget, expected_version)
    _require_status(budget, BudgetStatus.APPROVED, action="закрытие")
    if _draft_version(budget) is not None:
        raise DomainError("E-STATE-01", f"У бюджета {budget.number} открыта корректировка — "
                                        f"утвердите или отмените её.", status=409)
    pending = list(PurchaseRequest.objects.filter(
        project_id=budget.project_id, status=RequestStatus.ON_REVIEW)
        .values_list("number", flat=True)[:5])
    if pending:
        raise DomainError(
            "E-BUD-06",
            f"Бюджет {budget.number} нельзя закрыть: заявки на согласовании — "
            f"{', '.join(pending)}. Дождитесь решения или отзовите их.",
            status=409)
    budget.status, budget.status_comment = BudgetStatus.CLOSED, (comment or "")[:1000]
    _touch(budget, actor.user_id, "status", "status_comment")
    audit.record(budget, "closed", actor_id=actor.user_id, comment=comment or "")
    return budget


@transaction.atomic
def reopen(actor: Actor, budget_id, *, expected_version: int | None, comment: str) -> Budget:
    budget = _lock(budget_id)
    _require(actor, "bpp.budgets.approve", "edit", "на повторное открытие", budget)
    check_version(budget, expected_version)
    _require_status(budget, BudgetStatus.CLOSED, action="повторное открытие")
    comment = (comment or "").strip()
    if len(comment) < COMMENT_MIN:
        raise DomainError(
            "BR-060", f"Комментарий к открытию бюджета — не короче {COMMENT_MIN} символов.",
            fields=[{"field": "comment", "message": f"Минимум {COMMENT_MIN} символов"}])
    budget.status, budget.status_comment = BudgetStatus.APPROVED, comment
    _touch(budget, actor.user_id, "status", "status_comment")
    audit.record(budget, "reopened", actor_id=actor.user_id, comment=comment)
    return budget


@transaction.atomic
def delete_draft(actor: Actor, budget_id, *, expected_version: int | None) -> None:
    budget = _lock(budget_id)
    _require(actor, "bpp.budgets", "delete", "на удаление", budget)
    check_version(budget, expected_version)
    _require_status(budget, BudgetStatus.DRAFT, action="удаление")
    # Журнал сохраняет факт удаления (ТЗ §6.6): запись — до удаления, ключ
    # объекта в журнале остаётся.
    audit.record(budget, "deleted", actor_id=actor.user_id,
                 changes={"number": budget.number,
                          "lines": _snapshot(budget.versions.get(version_no=1))})
    budget.delete()
