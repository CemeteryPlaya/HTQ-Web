"""Заявка на закупку: черновик, отправка, отзыв, отмена, закрытие остатка
(ТЗ §07, §15.2, задача B2.2).

Отправка — одна транзакция (BR-011): блокировка строки бюджета → остаток без
самой заявки → сравнение → запуск ``signoff``. Колбэк ``on_started``
переводит заявку в «На согласовании» в той же транзакции, поэтому вторая
заявка, ждавшая блокировку строки, пересчитает «Задействовано» уже с
первой (AC-004).

Права — узел ``bpp.requests`` и группа статей роли инициатора (BR-010); ПМ
работает только по проектам-участиям (BR-014). Правит заявку только автор
и только в «Черновике» и «На доработке»; каждое изменение сначала спрашивает
``assert_editable`` (замок согласования, CLAUDE.md).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.bpp.models import (
    InitiatorRole,
    ItemStatus,
    PurchaseRequest,
    PurchaseRequestItem,
    PurchaseType,
    RequestStatus,
)
from apps.bpp.services.actor import ROLE_GROUP, Actor
from apps.bpp.services.budget import balance as budget_balance
from apps.bpp.services.core import audit
from apps.bpp.services.core import files as core_files
from apps.bpp.services.core.errors import check_version
from apps.bpp.services.core.numbering import next_number
from apps.bpp.services.money import fmt, line_amount
from apps.project import interface as projects
from apps.refdata import interface as refdata
from apps.signoff import interface as signoff
from htqweb.errors import DomainError

SUBJECT = PurchaseRequest.SIGNOFF_SUBJECT_TYPE
MAX_ITEMS = 200
COMMENT_MIN = 10
JUSTIFICATION_MIN, JUSTIFICATION_MAX = 10, 2000
EDITABLE = (RequestStatus.DRAFT, RequestStatus.REWORK)

#: Подписи обязательных полей для E-REQ-01 (ТЗ §26.1).
FIELD_LABELS = {
    "article_id": "Статья бюджета",
    "purchase_type": "Вид закупки",
    "need_date": "Потребность к дате",
    "justification": "Обоснование потребности",
    "items": "Позиции",
}


# ── права и видимость ───────────────────────────────────────────────────

def _deny(text: str) -> DomainError:
    return DomainError("E-ACC-01", f"{text} Если это ошибка, обратитесь к администратору.",
                       status=403)


def sees_all(actor: Actor) -> bool:
    """ТД, ОД, ФД, ГД и АДМ видят все заявки; СН и ПМ — только свои (ТЗ §7.1).

    Узел ``bpp.requests.all`` (``access/0017``) — тот же круг ролей, что
    раньше выводился из «просмотр без права создавать»; теперь совмещающий
    СН с ролью директора видит все заявки, а не только свои.
    """
    return actor.can("bpp.requests.all", "view")


def can_view(actor: Actor, req: PurchaseRequest) -> bool:
    if req.author_id == actor.user_id:
        return True
    if sees_all(actor):
        return True
    # Согласующий видит то, что согласует, даже без роли в модуле.
    return signoff.is_participant(actor.user_id, SUBJECT, str(req.pk))


def get_visible(actor: Actor, request_id) -> PurchaseRequest:
    req = PurchaseRequest.objects.filter(pk=request_id).first()
    if req is None or not can_view(actor, req):
        raise DomainError("E-NOT-FOUND", "Заявка не найдена.", status=404)
    return req


def _lock(request_id) -> PurchaseRequest:
    req = PurchaseRequest.objects.select_for_update().filter(pk=request_id).first()
    if req is None:
        raise DomainError("E-NOT-FOUND", "Заявка не найдена.", status=404)
    return req


def _require_author(actor: Actor, req: PurchaseRequest, action: str) -> None:
    if req.author_id != actor.user_id:
        raise _deny(f"{action} заявку {req.number} может только её автор.")


def _state_error(action: str, req: PurchaseRequest) -> DomainError:
    """E-STS-01 — переход не из таблицы ТЗ §15.2."""
    return DomainError(
        "E-STS-01",
        f"Нельзя {action} заявку {req.number} в статусе „{req.get_status_display()}“.",
        status=409)


def _require_status(req: PurchaseRequest, statuses, action: str) -> None:
    """``action`` — глагол: «отправить», «отозвать»…"""
    if req.status not in statuses:
        raise _state_error(action, req)


def allowed_actions(actor: Actor, req: PurchaseRequest) -> list[str]:
    """Кнопки формы F-02 (ТЗ §7.7) — по роли, авторству и статусу."""
    author = req.author_id == actor.user_id
    actions = []
    if author and req.status in EDITABLE:
        actions += ["save", "submit", "cancel"]
        if req.status == RequestStatus.DRAFT:
            actions.append("delete")
    if author and req.status == RequestStatus.IN_APPROVAL and not _has_decisions(req):
        actions.append("withdraw")
    if req.status == RequestStatus.APPROVED:
        if actor.can("bpp.requests.cancel_approved", "edit"):
            actions.append("cancel")
        if author or actor.can("bpp.requests.cancel_approved", "edit"):
            actions.append("close_remainder")
    if actor.initiator_roles():
        actions.append("copy")
    actions.append("print")
    return actions


# ── проверки полей ──────────────────────────────────────────────────────

def _role_for(actor: Actor, wanted: str | None) -> str:
    roles = actor.initiator_roles()
    if not roles:
        raise _deny("У вас нет роли, в которой подают заявки на закупку.")
    if not wanted:
        if len(roles) == 1:
            return roles[0]
        raise DomainError(
            "E-REQ-01", "Не удалось сохранить заявку. Не заполнено поле „Роль инициатора“. "
                        "Выберите роль и повторите.",
            fields=[{"field": "initiator_role", "message": "Выберите роль"}])
    if wanted not in roles:
        raise _deny(f"Роль „{InitiatorRole(wanted).label}“ вам не назначена.")
    return wanted


def _check_project(actor: Actor, role: str, project_id) -> dict:
    brief = projects.project_brief([str(project_id)]).get(str(project_id))
    if brief is None:
        raise DomainError("E-NOT-FOUND", "Проект не найден.", status=404,
                          fields=[{"field": "project_id", "message": "Проект не найден"}])
    if brief["status"] != "active":
        raise DomainError(
            "E-PRJ-03", f"Проект {brief['code']} не активен — заявки по нему не подаются.",
            fields=[{"field": "project_id", "message": "Проект не активен"}])
    # BR-014: ПМ — только проекты-участия; СН — все активные [У].
    if role == InitiatorRole.PM and not projects.is_member(str(project_id), actor.user_id):
        raise DomainError("E-REQ-05", f"Проект {brief['code']} вам недоступен.", status=403,
                          fields=[{"field": "project_id", "message": "Проект недоступен"}])
    budget_balance.approved_budget(project_id)  # BR-003 / E-BUD-02
    return brief


def _check_article(role: str, project_id, article_id) -> None:
    brief = refdata.article_brief([str(article_id)]).get(str(article_id))
    if brief is None:
        raise DomainError("E-NOT-FOUND", "Статья не найдена.", status=404,
                          fields=[{"field": "article_id", "message": "Статья не найдена"}])
    group = next((g for g in refdata.article_groups() if g["id"] == brief["group_id"]), None)
    if group is None or group["code"] != ROLE_GROUP[role]:
        # AC-002: чужая группа — 403, а не 422 (ТЗ §13.3).
        raise DomainError(
            "E-REQ-04",
            f"Статья „{brief['name']}“ недоступна для роли {InitiatorRole(role).label}.",
            status=403, fields=[{"field": "article_id", "message": "Статья чужой группы"}])
    if not brief["is_active"]:
        raise DomainError(
            "E-REF-03", f"Статья „{brief['name']}“ в архиве — новые заявки по ней не создаются.",
            fields=[{"field": "article_id", "message": "Статья в архиве"}])
    budget_balance.active_line(project_id, article_id)  # строки нет — E-BUD-07


def _clean_items(items: list[dict], default_date: date | None) -> list[dict]:
    """Строки позиций. Строка либо полная, либо её нет: в черновике можно не
    заполнять шапку, но позиция без количества или цены не хранится."""
    if len(items) > MAX_ITEMS:
        raise DomainError(
            "E-REQ-06", f"В заявке не больше {MAX_ITEMS} позиций.",
            fields=[{"field": "items", "message": f"Не больше {MAX_ITEMS}"}])
    uoms = refdata.uom_brief([str(item["uom_id"]) for item in items if item.get("uom_id")])
    cleaned = []
    for index, item in enumerate(items, start=1):
        where = f"items[{index - 1}]"

        def bad(field: str, text: str):
            return DomainError("E-VAL-01", f"Позиция {index}: {text}.",
                               fields=[{"field": f"{where}.{field}", "message": text}])

        name = (item.get("name") or "").strip()
        if not 3 <= len(name) <= 500:
            raise bad("name", "наименование — от 3 до 500 символов")
        uom = uoms.get(str(item.get("uom_id") or ""))
        if uom is None or not uom["is_active"]:
            raise bad("uom_id", "выберите единицу измерения из справочника")
        qty, price = Decimal(str(item.get("qty") or 0)), Decimal(str(item.get("price") or 0))
        if qty <= 0:
            raise bad("qty", "количество должно быть больше нуля")
        if price <= 0:
            raise bad("price", "цена должна быть больше нуля")
        need_date = item.get("need_date") or default_date
        if need_date is None:
            raise bad("need_date", "укажите дату потребности")
        cleaned.append({"name": name, "specs": (item.get("specs") or "")[:2000],
                        "uom_id": str(item["uom_id"]), "qty": qty, "price": price,
                        "amount": line_amount(qty, price), "need_date": need_date})
    return cleaned


def _write_items(req: PurchaseRequest, items: list[dict], actor_id: int) -> None:
    req.items.all().delete()
    PurchaseRequestItem.objects.bulk_create([
        PurchaseRequestItem(
            request=req, line_no=index, sys_number=f"{req.number}-{index:02d}",
            executor_id=req.author_id, created_by=actor_id, updated_by=actor_id, **item)
        for index, item in enumerate(items, start=1)
    ])
    req.total_amount = sum((item["amount"] for item in items), Decimal("0.00"))


def _apply_header(req: PurchaseRequest, data: dict) -> None:
    if "purchase_type" in data:
        req.purchase_type = data["purchase_type"] or ""
    if "need_date" in data:
        req.need_date = data["need_date"] or None
    if "justification" in data:
        req.justification = (data["justification"] or "").strip()[:JUSTIFICATION_MAX]
    if "article_id" in data:
        req.article_id = data["article_id"] or None


def _snapshot(req: PurchaseRequest) -> dict:
    return {
        "project_id": str(req.project_id), "article_id": str(req.article_id or ""),
        "purchase_type": req.purchase_type, "need_date": str(req.need_date or ""),
        "total_amount": str(req.total_amount),
        "items": [{"line_no": i.line_no, "name": i.name, "qty": str(i.qty),
                   "price": str(i.price), "amount": str(i.amount)} for i in req.items.all()],
    }


def _touch(req: PurchaseRequest, actor_id: int, *fields: str) -> None:
    req.version += 1
    req.updated_by = actor_id
    req.save(update_fields=[*fields, "version", "updated_by", "updated_at"])


# ── черновик ────────────────────────────────────────────────────────────

@transaction.atomic
def create_draft(actor: Actor, data: dict) -> PurchaseRequest:
    role = _role_for(actor, data.get("initiator_role"))
    if not data.get("project_id"):
        raise DomainError(
            "E-REQ-01", "Не удалось сохранить заявку. Не заполнено поле „Проект“. "
                        "Выберите проект и повторите.",
            fields=[{"field": "project_id", "message": "Выберите проект"}])
    _check_project(actor, role, data["project_id"])
    if data.get("article_id"):
        _check_article(role, data["project_id"], data["article_id"])
    budget = budget_balance.approved_budget(data["project_id"])
    items = _clean_items(data.get("items") or [], data.get("need_date"))
    req = PurchaseRequest(
        number=next_number("ЗЗ"), author_id=actor.user_id, initiator_role=role,
        project_id=data["project_id"], currency_code=budget.currency_code,
        created_by=actor.user_id, updated_by=actor.user_id)
    _apply_header(req, data)
    req.save()
    _write_items(req, items, actor.user_id)
    req.save(update_fields=["total_amount"])
    audit.record(req, "created", actor_id=actor.user_id, changes=_snapshot(req))
    return req


@transaction.atomic
def update_draft(actor: Actor, request_id, *, expected_version: int | None,
                 data: dict) -> PurchaseRequest:
    req = _lock(request_id)
    req.assert_editable()
    _require_author(actor, req, "Править")
    _require_status(req, EDITABLE, "править")
    check_version(req, expected_version)
    before = _snapshot(req)
    role = req.initiator_role
    if data.get("initiator_role") and data["initiator_role"] != req.initiator_role:
        role = _role_for(actor, data["initiator_role"])
        req.initiator_role = role
        req.article_id = None  # смена роли очищает статью (ТЗ §7.3)
    if data.get("project_id") and str(data["project_id"]) != str(req.project_id):
        _check_project(actor, role, data["project_id"])
        req.project_id = data["project_id"]
        req.article_id = None  # смена проекта очищает статью (ТЗ §7.3)
    _apply_header(req, data)
    if req.article_id:
        _check_article(role, req.project_id, req.article_id)
    if "items" in data:
        _write_items(req, _clean_items(data["items"] or [], req.need_date), actor.user_id)
    _touch(req, actor.user_id, "initiator_role", "project_id", "article_id", "purchase_type",
           "need_date", "justification", "total_amount")
    audit.record(req, "updated", actor_id=actor.user_id,
                 changes={"before": before, "after": _snapshot(req)})
    return req


@transaction.atomic
def delete_draft(actor: Actor, request_id, *, expected_version: int | None) -> None:
    req = _lock(request_id)
    req.assert_editable()
    _require_author(actor, req, "Удалить")
    _require_status(req, (RequestStatus.DRAFT,), "удалить")
    check_version(req, expected_version)
    audit.record(req, "deleted", actor_id=actor.user_id, changes=_snapshot(req))
    # Файлы черновика — в apps.files: ни разу не отправленная заявка уносит
    # их физически, отправлявшаяся (отозванная) оставляет с пометкой (ТЗ §21).
    core_files.owner_deleted(req, actor_id=actor.user_id)
    req.delete()


# ── отправка ────────────────────────────────────────────────────────────

def _required_missing(req: PurchaseRequest) -> list[str]:
    missing = []
    if not req.article_id:
        missing.append("article_id")
    if not req.purchase_type:
        missing.append("purchase_type")
    if not req.need_date:
        missing.append("need_date")
    if len(req.justification.strip()) < JUSTIFICATION_MIN:
        missing.append("justification")
    if not req.items.exists() or req.total_amount <= 0:
        missing.append("items")
    return missing


def _check_required(req: PurchaseRequest) -> None:
    missing = _required_missing(req)
    if missing:
        label = FIELD_LABELS[missing[0]]
        raise DomainError(
            "E-REQ-01",
            f"Не удалось отправить заявку. Не заполнено поле „{label}“. Заполните его и "
            f"повторите отправку.",
            fields=[{"field": field, "message": f"Не заполнено поле „{FIELD_LABELS[field]}“"}
                    for field in missing])
    today = timezone.localdate()
    late = [item.sys_number for item in req.items.all() if item.need_date < today]
    if req.need_date < today or late:
        raise DomainError(
            "E-VAL-01", "Дата потребности не может быть в прошлом"
                        + (f" (позиции {', '.join(late)})." if late else "."),
            fields=[{"field": "need_date", "message": "Дата ≥ сегодня"}])


def _signoff_error(exc: Exception) -> DomainError:
    return DomainError("E-SGN-01", str(exc), status=409)


@transaction.atomic
def submit(actor: Actor, request_id, *, expected_version: int | None) -> PurchaseRequest:
    req = _lock(request_id)
    req.assert_editable()
    _require_author(actor, req, "Отправить")
    _require_status(req, EDITABLE, "отправить")
    check_version(req, expected_version)
    _check_required(req)
    if req.initiator_role not in actor.initiator_roles():
        raise _deny(f"Роль „{req.get_initiator_role_display()}“ вам больше не назначена.")
    _check_project(actor, req.initiator_role, req.project_id)
    _check_article(req.initiator_role, req.project_id, req.article_id)
    # BR-011 под блокировкой строки бюджета.
    line = budget_balance.lock_line(req.project_id, req.article_id)
    figures = budget_balance.balance(req.project_id, req.article_id,
                                     exclude_request_id=req.pk)
    if req.total_amount > figures["available"]:
        over = req.total_amount - figures["available"]
        raise DomainError(
            "E-BUD-01",
            f"Сумма заявки {fmt(req.total_amount, req.currency_code)} превышает доступный остаток "
            f"статьи „{budget_balance.article_name(req.article_id)}“ "
            f"({fmt(figures['available'], req.currency_code)}) на {fmt(over, req.currency_code)}. "
            f"Уменьшите сумму или обратитесь к финансовому директору за корректировкой лимита.",
            fields=[{"field": "items", "message": "Сумма превышает остаток",
                     "available": str(figures["available"]), "over": str(over)}])
    try:
        signoff.start_process(subject_type=SUBJECT, subject_id=str(req.pk),
                              initiator_id=actor.user_id)
    except signoff.SignoffError as exc:
        raise _signoff_error(exc) from exc
    req.refresh_from_db()
    req.status_comment = ""
    _touch(req, actor.user_id, "status_comment")
    audit.record(req, "submitted", actor_id=actor.user_id,
                 changes={"total_amount": str(req.total_amount),
                          "available_before": str(figures["available"]),
                          "budget_line": str(line.pk)})
    return req


def _process(req: PurchaseRequest) -> dict | None:
    return signoff.get_process_for(SUBJECT, str(req.pk))


def _has_decisions(req: PurchaseRequest) -> bool:
    process = _process(req)
    if process is None or process["state"] != "pending":
        return False
    return any(task["state"] in ("approved", "rejected", "rework")
               for stage in process["stages"] for task in stage["tasks"])


@transaction.atomic
def withdraw(actor: Actor, request_id, *, expected_version: int | None) -> PurchaseRequest:
    req = _lock(request_id)
    _require_author(actor, req, "Отозвать")
    _require_status(req, (RequestStatus.IN_APPROVAL,), "отозвать")
    check_version(req, expected_version)
    if _has_decisions(req):
        raise DomainError(
            "E-STS-01", f"Нельзя отозвать заявку {req.number}: по ней уже есть решение. "
                        f"Попросите согласующего вернуть её на доработку.",
            status=409)
    process = _process(req)
    try:
        signoff.cancel_process(process_id=process["id"], actor_id=actor.user_id)
    except signoff.SignoffError as exc:
        raise _signoff_error(exc) from exc
    req.refresh_from_db()
    _touch(req, actor.user_id)
    audit.record(req, "withdrawn", actor_id=actor.user_id)
    return req


def _comment(comment: str, action: str) -> str:
    comment = (comment or "").strip()
    if len(comment) < COMMENT_MIN:
        raise DomainError(
            "BR-060", "Опишите причину: комментарий не короче 10 символов.",
            fields=[{"field": "comment", "message": f"Минимум {COMMENT_MIN} символов"}])
    return comment


def _in_documents(req: PurchaseRequest) -> bool:
    """Есть ли позиции заявки в договорах или счетах (этап 3, B3.1/B3.2)."""
    return False


@transaction.atomic
def cancel(actor: Actor, request_id, *, expected_version: int | None,
           comment: str) -> PurchaseRequest:
    """Отменить: автор — черновик и доработку; ФД — утверждённую без
    договоров и счетов (ТЗ §15.2). Позиции аннулируются, резерв снят."""
    req = _lock(request_id)
    comment = _comment(comment, "Отмена заявки")
    check_version(req, expected_version)
    if req.status in EDITABLE:
        _require_author(actor, req, "Отменить")
    elif req.status == RequestStatus.APPROVED:
        if not actor.can("bpp.requests.cancel_approved", "edit"):
            raise _deny(f"Утверждённую заявку {req.number} отменяет финансовый директор.")
        if _in_documents(req):
            raise DomainError(
                "E-STS-01", f"Нельзя отменить заявку {req.number}: по её позициям уже есть "
                            f"договоры или счета. Закройте остаток.", status=409)
    else:
        _require_status(req, (*EDITABLE, RequestStatus.APPROVED), "отменить")
    req.items.update(status=ItemStatus.ANNULLED)
    req.status, req.status_comment = RequestStatus.CANCELLED, comment
    _touch(req, actor.user_id, "status", "status_comment")
    audit.record(req, "cancelled", actor_id=actor.user_id, comment=comment)
    return req


@transaction.atomic
def close_remainder(actor: Actor, request_id, *, expected_version: int | None,
                    comment: str) -> PurchaseRequest:
    """«Закрыть остаток» (ТЗ §7.7): невыбранные остатки позиций аннулируются,
    резерв падает до выставленных счетов, заявка — «Закрыта». До этапа 3
    счетов нет: открытые позиции аннулируются целиком."""
    req = _lock(request_id)
    comment = _comment(comment, "Закрытие остатка")
    check_version(req, expected_version)
    _require_status(req, (RequestStatus.APPROVED,), "закрыть остаток")
    if req.author_id != actor.user_id and not actor.can("bpp.requests.cancel_approved", "edit"):
        raise _deny(f"Закрыть остаток заявки {req.number} может автор или финансовый директор.")
    req.items.filter(status=ItemStatus.OPEN).update(status=ItemStatus.ANNULLED)
    req.items.filter(status=ItemStatus.PARTIALLY_CLOSED).update(status=ItemStatus.CLOSED)
    req.status, req.status_comment = RequestStatus.CLOSED, comment
    _touch(req, actor.user_id, "status", "status_comment")
    audit.record(req, "remainder_closed", actor_id=actor.user_id, comment=comment)
    return req


@transaction.atomic
def copy(actor: Actor, request_id) -> PurchaseRequest:
    """Новая заявка «Черновик» с теми же шапкой и позициями, без файлов и
    согласований (ТЗ §7.7). Роль — своя: копирует и тот, кто не автор."""
    source = get_visible(actor, request_id)
    roles = actor.initiator_roles()
    wanted = source.initiator_role if source.initiator_role in roles else None
    today = timezone.localdate()
    # Статья переносится как есть: копирующий в другой роли получит на ней
    # 403 E-REQ-04 (BR-010), а не заявку с молча выброшенной статьёй.
    data = {
        "initiator_role": wanted or (roles[0] if len(roles) == 1 else None),
        "project_id": str(source.project_id),
        "article_id": str(source.article_id) if source.article_id else None,
        "purchase_type": source.purchase_type,
        "need_date": source.need_date if source.need_date and source.need_date >= today else None,
        "justification": source.justification,
        "items": [{"name": i.name, "specs": i.specs, "uom_id": str(i.uom_id), "qty": i.qty,
                   "price": i.price,
                   "need_date": i.need_date if i.need_date >= today else today}
                  for i in source.items.all()],
    }
    req = create_draft(actor, data)
    audit.record(req, "copied", actor_id=actor.user_id, changes={"source": source.number})
    return req


# ── колбэки согласования (approval_hooks) ───────────────────────────────

def on_started(request_id) -> None:
    PurchaseRequest.objects.filter(pk=request_id).update(status=RequestStatus.IN_APPROVAL)


def on_approved(request_id) -> None:
    # Позиции остаются открытыми и попадают в План закупок автора (AC-003).
    PurchaseRequest.objects.filter(pk=request_id).update(status=RequestStatus.APPROVED)


def on_rejected(request_id) -> None:
    PurchaseRequest.objects.filter(pk=request_id).update(status=RequestStatus.REJECTED)
    PurchaseRequestItem.objects.filter(request_id=request_id).update(status=ItemStatus.ANNULLED)


def _last_rework_comment(request_id) -> str:
    process = signoff.get_process_for(SUBJECT, str(request_id))
    comments = [task.get("comment") or "" for stage in (process or {}).get("stages", [])
                for task in stage["tasks"] if task["state"] == "rework"]
    return comments[-1] if comments else ""


def on_rework(request_id) -> None:
    """Возврат на доработку — и на ходу, и уже закрытого круга
    (``signoff.rework_process``): аннулированные отказом позиции снова открыты,
    комментарий согласующего — в ``rework_comment`` (жёлтая плашка, ТЗ §7.6)."""
    PurchaseRequest.objects.filter(pk=request_id).update(
        status=RequestStatus.REWORK, rework_comment=_last_rework_comment(request_id))
    PurchaseRequestItem.objects.filter(request_id=request_id,
                                       status=ItemStatus.ANNULLED).update(status=ItemStatus.OPEN)


def on_cancelled(request_id) -> None:
    PurchaseRequest.objects.filter(pk=request_id).update(status=RequestStatus.DRAFT)


def purchase_type_label(value: str) -> str:
    return PurchaseType(value).label if value else ""
