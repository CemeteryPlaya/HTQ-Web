"""Стык заявки на закупку с тендерным модулем — пакет B-1 (T1.2; пошаговый
план 2026-10-07 §2, мастер-план tender T-07, T-09, T-20, §3.4).

ЗЗ с ``source="tender"`` заводит, отправляет, отзывает, отменяет и
закрывает только этот модуль — через ``bpp.interface``; сервисы и API БЗО
на ней отвечают 409 ``E-STS-02`` (замок ``requests._guard_tender``). Здесь
замок снимается флагом ``via_tender=True``, всё остальное — права, группы
статей (BR-010), проект (BR-014), остаток под блокировкой строки (BR-011),
журнал — штатное: работает пользователь tender (закупщик, T-20) под своими
ролями БЗО, ``Actor.for_user`` в текущей компании.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from django.db import transaction

from apps.bpp.models import BudgetLine, PurchaseRequest, RequestSource, RequestStatus
from apps.bpp.schemas.tender import (
    BudgetArticle,
    BudgetFigures,
    RequestRef,
    RequestStatusOut,
    TenderActor,
    TenderPartIn,
    TenderRequestSubmit,
)
from apps.bpp.services.actor import ROLE_GROUP, Actor
from apps.bpp.services.budget import balance as budget_balance
from apps.bpp.services.budget import committed as calc
from apps.bpp.services.core import audit
from apps.refdata import interface as refdata
from htqweb.errors import DomainError
from htqweb.tenancy import current_company

from . import listeners
from . import requests as service

ZERO = Decimal("0.00")


def _actor(actor: TenderActor | dict) -> Actor:
    actor = TenderActor.model_validate(actor)
    return Actor.for_user(actor.user_id, company=current_company(),
                          is_superuser=actor.is_superuser)


def _uuid(value) -> str | None:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError, AttributeError):
        return None


def _not_found() -> DomainError:
    return DomainError("E-NOT-FOUND", "Заявка не найдена.", status=404)


def _locked_rows(ids) -> list[PurchaseRequest]:
    """ЗЗ tender под блокировкой строк (порядок — по ключу, без взаимных
    блокировок); невозможный, несуществующий или не тендерный ключ — 404."""
    keys = {_uuid(value) for value in ids}
    if None in keys:
        raise _not_found()
    rows = list(PurchaseRequest.objects.select_for_update()
                .filter(pk__in=keys, source=RequestSource.TENDER).order_by("pk"))
    if len(rows) != len(keys):
        raise _not_found()
    return rows


# ── отправка ────────────────────────────────────────────────────────────

def _fields(data: TenderRequestSubmit, part: TenderPartIn) -> dict:
    return {
        "initiator_role": data.initiator_role, "project_id": data.project_id,
        "article_id": part.article_id, "purchase_type": part.purchase_type,
        "need_date": data.need_date, "justification": data.justification,
        "items": [item.model_dump() for item in part.items],
    }


def _submit_part(actor: Actor, data: TenderRequestSubmit, part: TenderPartIn) -> RequestRef:
    fields = _fields(data, part)
    if part.bpp_request_id is None:
        req = service.create_draft(actor, fields, source=RequestSource.TENDER,
                                   tender_number=data.tender_number)
    else:
        key = _uuid(part.bpp_request_id)
        if key is None or not PurchaseRequest.objects.filter(
                pk=key, source=RequestSource.TENDER,
                tender_number=data.tender_number).exists():
            raise _not_found()
        # Повтор на доработке пересобирает позиции той же ЗЗ; не «Черновик» и
        # не «На доработке» — E-STS-01 штатно.
        req = service.update_draft(actor, key, expected_version=None, data=fields,
                                   via_tender=True)
    req = service.submit(actor, req.pk, expected_version=None, via_tender=True)
    return RequestRef(key=part.key, bpp_request_id=str(req.pk), number=req.number,
                      status=req.status,
                      items=[str(pk) for pk in req.items.order_by("line_no")
                             .values_list("pk", flat=True)])


@transaction.atomic
def submit_from_tender(data: TenderRequestSubmit | dict) -> list[RequestRef]:
    """По части — новая ЗЗ или пересборка существующей, затем отправка; одна
    транзакция на все части. Ошибка части откатывает все и уходит наружу
    штатным ``DomainError`` с ``details={"part": key}`` (то же — в каждом
    элементе ``fields``, чтобы ключ части дошёл и до HTTP-ответа)."""
    data = TenderRequestSubmit.model_validate(data)
    actor = _actor(data.actor)
    refs = []
    for part in data.parts:
        try:
            refs.append(_submit_part(actor, data, part))
        except DomainError as exc:
            exc.details = {"part": part.key}
            for field in exc.fields:
                field.setdefault("part", part.key)
            raise
    return refs


# ── отзыв, отмена, возврат в План ───────────────────────────────────────

@transaction.atomic
def withdraw_from_tender(ids, *, actor: TenderActor | dict) -> None:
    """Отзыв каждой ЗЗ «На согласовании» (решений по ней ещё нет — иначе
    E-STS-01 и откат всех); прочие статусы не трогаются."""
    who = _actor(actor)
    for req in _locked_rows(ids):
        if req.status == RequestStatus.IN_APPROVAL:
            service.withdraw(who, req.pk, expected_version=None, via_tender=True)


@transaction.atomic
def cancel_from_tender(ids, *, actor: TenderActor | dict, comment: str) -> None:
    """«Черновик»/«На доработке» — отмена; «Утверждена» — «Закрыть остаток»
    (автор вправе, резерв снимается); «На согласовании» — 409 E-STS-01
    (сначала отозвать); «Отклонена», «Отменена», «Закрыта» — пропуск."""
    who = _actor(actor)
    rows = _locked_rows(ids)
    busy = next((req for req in rows if req.status == RequestStatus.IN_APPROVAL), None)
    if busy is not None:
        raise service._state_error("отменить", busy)
    for req in rows:
        if req.status in service.EDITABLE:
            service.cancel(who, req.pk, expected_version=None, comment=comment,
                           via_tender=True)
        elif req.status == RequestStatus.APPROVED:
            service.close_remainder(who, req.pk, expected_version=None, comment=comment,
                                    via_tender=True)


@transaction.atomic
def release_to_plan(ids, *, actor: TenderActor | dict) -> None:
    """«Тендер не состоялся» (этап 2): признак ``source`` снимается, позиции
    утверждённой ЗЗ видны в Плане у исполнителя; номер тендерной заявки
    остаётся — по нему tender читает статус. Только «Утверждена»."""
    who = _actor(actor)
    rows = _locked_rows(ids)
    wrong = next((req for req in rows if req.status != RequestStatus.APPROVED), None)
    if wrong is not None:
        raise service._state_error("вернуть в План", wrong)
    for req in rows:
        req.source = RequestSource.BPP
        service._touch(req, who.user_id, "source")
        audit.record(req, "released_to_plan", actor_id=who.user_id,
                     changes={"source": [RequestSource.TENDER.value, ""],
                              "tender_number": req.tender_number})


# ── чтение ──────────────────────────────────────────────────────────────

def request_status(ids) -> dict[str, RequestStatusOut]:
    """Статусы ЗЗ, заведённых tender (в том числе возвращённых в План — у них
    остаётся ``tender_number``). Невозможные, несуществующие и чужие ключи в
    ответ не попадают."""
    keys = [key for key in (_uuid(value) for value in ids) if key]
    rows = {str(req.pk): req for req in PurchaseRequest.objects.filter(pk__in=keys)
            .exclude(source=RequestSource.BPP, tender_number="")}
    return {key: listeners.status_out(rows[key]) for key in dict.fromkeys(keys)
            if key in rows}


def _project_key(project_id) -> str:
    key = _uuid(project_id)
    if key is None:
        raise DomainError("E-NOT-FOUND", "Проект не найден.", status=404,
                          fields=[{"field": "project_id", "message": "Проект не найден"}])
    return key


def _role(who: Actor, role: str) -> str:
    """Роль инициатора, в которой tender спрашивает бюджет: не назначена — 403."""
    if role not in ROLE_GROUP:
        raise DomainError("E-VAL-01", "Неизвестная роль инициатора.",
                          fields=[{"field": "role", "message": "sn или pm"}])
    return service._role_for(who, role)


def budget_available(project_id, article_id, *, actor: TenderActor | dict,
                     role: str) -> BudgetFigures:
    """Остаток статьи по действующей версии бюджета (``balance.balance``) —
    с правами пользователя, как у заявки: роль назначена, ПМ — только
    проекты-участия (403 E-REQ-05, BR-014), статья из группы роли (403
    E-REQ-04, BR-010), в архиве — E-REF-03; нет утверждённого бюджета —
    E-BUD-02, нет строки — E-BUD-07."""
    who = _actor(actor)
    role = _role(who, role)
    project_id = _project_key(project_id)
    article_key = _uuid(article_id)
    if article_key is None:
        raise DomainError("E-NOT-FOUND", "Статья не найдена.", status=404,
                          fields=[{"field": "article_id", "message": "Статья не найдена"}])
    service._check_project(who, role, project_id)
    service._check_article(role, project_id, article_key)
    figures = budget_balance.balance(project_id, article_key)
    budget = budget_balance.approved_budget(project_id)
    return BudgetFigures(limit=figures["limit"], committed=figures["committed"],
                         available=figures["available"], currency_code=budget.currency_code)


def budget_articles(project_id, *, actor: TenderActor | dict, role: str) -> list[BudgetArticle]:
    """Статьи утверждённого бюджета проекта из группы роли (BR-010), с
    остатком; действующие, по коду. Роль не назначена — 403, проект
    недоступен ПМ — 403 E-REQ-05, бюджета нет — E-BUD-02 (как у заявки)."""
    who = _actor(actor)
    role = _role(who, role)
    project_id = _project_key(project_id)
    service._check_project(who, role, project_id)
    budget = budget_balance.approved_budget(project_id)
    lines = {str(line.article_id): line
             for line in BudgetLine.objects.filter(version_id=budget.active_version_id)}
    briefs = refdata.article_brief(list(lines))
    groups = {group["id"]: group["code"] for group in refdata.article_groups()}
    wanted = ROLE_GROUP[role]
    committed = calc.committed_by_article(project_id, list(lines))
    out = []
    for key, line in lines.items():
        brief = briefs.get(key)
        if brief is None or not brief["is_active"] or groups.get(brief["group_id"]) != wanted:
            continue
        out.append(BudgetArticle(id=key, code=brief["code"], name=brief["name"],
                                 group_code=wanted,
                                 available=line.limit_amount - committed.get(key, ZERO)))
    return sorted(out, key=lambda article: article.code)
