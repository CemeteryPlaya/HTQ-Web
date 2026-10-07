"""Отправка заявки tender в БЗО, отзыв, отмена и «исключить часть» (T1.3;
план этапов 0–2, §3.2–§3.4; мастер-план T-03…T-08, T-20).

**Части (T-03).** Основные позиции группируются по статье (``item.article_id``
или статья заявки) — часть ``goods`` с видом заявки; доставка (``needs_delivery``)
и СМР (``needs_works``) — отдельные части видом «работы» на свои статьи, по
одной позиции qty 1, ед. «Услуга», цена — плановая сумма (T-04). Под каждой
частью — ЗЗ в БЗО: ``bpp.submit_request_from_tender`` заводит или пересобирает
их и отправляет одной транзакцией; ошибка любой части откатывает всё, и ответ
указывает на поле формы этой части.

**Повторная отправка** (после отзыва или возврата). ЗЗ в «Черновике» и «На
доработке» пересобираются; идущие и утверждённые не трогаются — их состав
сверяется с отправленным (отпечаток в журнале ``submitted``), правка — 422
``E-TND-03``. Часть, чьих позиций в заявке больше нет, отменяется в БЗО и
исчезает; позиции исключённой части добавить нельзя (``E-TND-03``).

Права БЗО — закупщика (T-20): ЗЗ подаётся от его имени, в роли заявки; группа
статей роли (T-06, BR-010) проверяется здесь же, до БЗО — 422 ``E-REQ-04``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from django.db import transaction
from django.utils import timezone

from apps.bpp import interface as bpp
from apps.refdata import interface as refdata
from apps.tender.models import (
    AuditLog,
    InitiatorRole,
    PartKind,
    TenderRequest,
    TenderRequestItem,
    TenderRequestPart,
    TenderRequestStatus,
)
from apps.tender.services.core import audit
from apps.tender.services.core.errors import check_version
from htqweb.errors import DomainError

from . import crud
from .status import ROLLED, active_parts, acting_on, excludable_parts, rolled_status

JUSTIFICATION_MIN = 10
COMMENT_MIN = 10
NAME_MAX, SPECS_MAX = 500, 2000
DELIVERY_NAME = "Доставка до объекта"
DROP_REASON = "Позиции этой статьи убраны из заявки при повторной отправке"

#: ЗЗ части в этих статусах пересобирается при отправке.
REBUILT = ("", "draft", "rework")
#: ЗЗ части в этих статусах не трогается: её состав зафиксирован.
LOCKED = ("in_approval", "approved")

LABELS = {
    "justification": "Обоснование потребности",
    "need_date": "Потребность к дате",
    "items": "Позиции",
    "article_id": "Статья бюджета",
    "delivery_article_id": "Статья доставки",
    "delivery_plan_amount": "Плановая сумма доставки",
    "works_scope": "Объём работ",
    "works_article_id": "Статья СМР",
    "works_plan_amount": "Плановая сумма СМР",
}
PART_LABELS = {PartKind.GOODS: "позиции", PartKind.DELIVERY: "доставка",
               PartKind.WORKS: "СМР"}


def tender_actor(ctx: crud.Ctx):
    return bpp.TenderActor(user_id=ctx.user_id,
                           is_superuser=bool(getattr(ctx.token, "is_superuser", False)))


def _own(ctx: crud.Ctx, request_id, expected_version, action: str, statuses) -> TenderRequest:
    """Заявка автора под блокировкой, в допустимом статусе и свежей версии."""
    crud.require(ctx, "edit")
    req = crud.get_visible(ctx, request_id, lock=True)
    if req.author_id != ctx.user_id:
        raise crud._deny(f"{action[:1].upper()}{action[1:]} заявку {req.number} может только "
                         f"её автор.")
    if req.status not in statuses:
        raise crud._state_error(action, req)
    check_version(req, expected_version)
    return req


def _tnd03(text: str, field_name: str) -> DomainError:
    return DomainError("E-TND-03", text, fields=[{"field": field_name, "message": text}])


# ── план частей ─────────────────────────────────────────────────────────

@dataclass
class Plan:
    """Часть, которую соберёт отправка: ``kind`` × статья."""

    kind: str
    article_id: str
    purchase_type: str
    #: Поле формы со статьёй части и поле её позиций/суммы — для ошибок.
    article_field: str
    items_field: str
    lines: list[dict] = field(default_factory=list)
    #: Позиции заявки (только ``goods``) и их индексы в форме (``items[i]``).
    items: list[TenderRequestItem] = field(default_factory=list)
    indexes: list[int] = field(default_factory=list)
    part: TenderRequestPart | None = None

    @property
    def key(self) -> tuple[str, str]:
        return self.kind, self.article_id

    def fingerprint(self) -> list:
        return [[line["name"], line["specs"], line["uom_id"], str(line["qty"]),
                 str(line["price"]), line["need_date"].isoformat()] for line in self.lines]


def _missing(req: TenderRequest, items: list[TenderRequestItem]) -> list[str]:
    missing = []
    if len(req.justification.strip()) < JUSTIFICATION_MIN:
        missing.append("justification")
    if not req.need_date:
        missing.append("need_date")
    if not items:
        missing.append("items")
    elif not req.article_id:
        missing += [f"items[{i}].article_id" for i, item in enumerate(items)
                    if not item.article_id]
    if req.needs_delivery:
        missing += [name for name in ("delivery_article_id", "delivery_plan_amount")
                    if not getattr(req, name)]
    if req.needs_works:
        if not req.works_scope.strip():
            missing.append("works_scope")
        missing += [name for name in ("works_article_id", "works_plan_amount")
                    if not getattr(req, name)]
    return missing


def _check_required(req: TenderRequest, items: list[TenderRequestItem]) -> None:
    """E-REQ-01 (T-04, T-05): все незаполненные поля — в ``fields``."""
    missing = _missing(req, items)
    if not missing:
        return
    label = LABELS.get(missing[0], LABELS["article_id"])
    raise DomainError(
        "E-REQ-01",
        f"Не удалось отправить заявку. Не заполнено поле „{label}“. Заполните его и "
        f"повторите отправку.",
        fields=[{"field": name,
                 "message": f"Не заполнено поле „{LABELS.get(name, LABELS['article_id'])}“"}
                for name in missing])


def _service_uom() -> str:
    uom = refdata.uom_id("service")
    if uom is None:
        raise DomainError("E-REF-03", "В справочнике единиц измерения нет действующей "
                                      "единицы «Услуга» — обратитесь к администратору.")
    return uom


def _plans(req: TenderRequest, items: list[TenderRequestItem]) -> list[Plan]:
    plans: dict[tuple[str, str], Plan] = {}
    for index, item in enumerate(items):
        article = str(item.article_id or req.article_id)
        plan = plans.get((PartKind.GOODS, article))
        if plan is None:
            plan = plans[(PartKind.GOODS, article)] = Plan(
                PartKind.GOODS, article, req.purchase_type,
                article_field=f"items[{index}].article_id" if item.article_id else "article_id",
                items_field="items")
        plan.items.append(item)
        plan.indexes.append(index)
        plan.lines.append({"name": item.name, "specs": item.specs, "uom_id": str(item.uom_id),
                           "qty": item.qty, "price": item.plan_price,
                           "need_date": item.need_date or req.need_date})
    out = list(plans.values())
    if req.needs_delivery:
        out.append(Plan(PartKind.DELIVERY, str(req.delivery_article_id), "works",
                        article_field="delivery_article_id",
                        items_field="delivery_plan_amount",
                        lines=[{"name": DELIVERY_NAME,
                                "specs": req.delivery_address[:SPECS_MAX],
                                "uom_id": _service_uom(), "qty": 1,
                                "price": req.delivery_plan_amount,
                                "need_date": req.need_date}]))
    if req.needs_works:
        scope = req.works_scope.strip()
        name = f"СМР: {scope}"
        out.append(Plan(PartKind.WORKS, str(req.works_article_id), "works",
                        article_field="works_article_id", items_field="works_plan_amount",
                        lines=[{"name": name[:NAME_MAX],
                                "specs": scope[:SPECS_MAX] if len(name) > NAME_MAX else "",
                                "uom_id": _service_uom(), "qty": 1,
                                "price": req.works_plan_amount,
                                "need_date": req.need_date}]))
    return out


def _check_groups(role: str, plans: list[Plan]) -> None:
    """T-06 (BR-010): статьи частей — из группы статей роли заявки; иначе 422
    ``E-REQ-04`` ещё в tender, до БЗО."""
    briefs = refdata.article_brief([plan.article_id for plan in plans])
    groups = {group["id"]: group["code"] for group in refdata.article_groups()}
    wanted = crud.ROLE_GROUP[role]
    for plan in plans:
        brief = briefs.get(plan.article_id)
        if brief is None:
            raise crud._bad(plan.article_field, "статья не найдена")
        if groups.get(brief["group_id"]) != wanted:
            text = f"Статья „{brief['name']}“ недоступна для роли {InitiatorRole(role).label}."
            raise DomainError("E-REQ-04", text,
                              fields=[{"field": plan.article_field, "message": text}])


def _last_sent(req: TenderRequest) -> dict:
    row = (AuditLog.objects.filter(object_type=crud.OBJECT_TYPE, object_id=str(req.pk),
                                   action="submitted")
           .order_by("-created_at").first())
    return row.changes if row else {}


def _part_name(plan: Plan, brief: dict | None) -> str:
    article = brief["name"] if brief else plan.article_id
    return f"{PART_LABELS[plan.kind]} по статье „{article}“"


def _match(req: TenderRequest, plans: list[Plan]) -> tuple[list[Plan], list[TenderRequestPart]]:
    """Сопоставить план с частями прошлых отправок: ``(к отправке, к отмене)``."""
    parts = {(p.kind, str(p.article_id)): p for p in req.parts.all()}
    last = _last_sent(req)
    sent_prints = last.get("parts", {})
    briefs = refdata.article_brief([plan.article_id for plan in plans])
    send: list[Plan] = []
    locked = False
    for plan in plans:
        part = parts.get(plan.key)
        plan.part = part
        name = _part_name(plan, briefs.get(plan.article_id))
        if part is None:
            send.append(plan)
        elif part.excluded_at is not None:
            raise _tnd03(f"Часть заявки ({name}) исключена: ЗЗ {part.bpp_number} отклонена. "
                         f"Добавить её позиции снова нельзя.", plan.article_field)
        elif part.bpp_status in REBUILT:
            send.append(plan)
        elif part.bpp_status in LOCKED:
            locked = True
            if sent_prints.get(str(part.pk)) != plan.fingerprint():
                raise _tnd03(f"Часть заявки ({name}) — ЗЗ {part.bpp_number} уже на "
                             f"согласовании или утверждена, её позиции не меняются. Верните "
                             f"прежние значения.", plan.items_field)
        else:
            raise _tnd03(f"Часть заявки ({name}) — ЗЗ {part.bpp_number} в статусе "
                         f"„{part.bpp_status}“, её не отправить снова.", plan.article_field)
    wanted = {plan.key for plan in plans}
    dropped = [p for key, p in parts.items() if key not in wanted and p.excluded_at is None]
    for part in dropped:
        if part.bpp_status in LOCKED:
            locked = True
            raise _tnd03(f"ЗЗ {part.bpp_number} уже на согласовании или утверждена — её "
                         f"позиции из заявки не убираются.", "items")
    if locked and (last.get("project_id"), last.get("initiator_role")) != (
            str(req.project_id), req.initiator_role):
        raise _tnd03("Часть заявки уже на согласовании или утверждена — проект и роль "
                     "инициатора не меняются.", "project_id")
    return send, dropped


def _for_part(exc: DomainError, plan: Plan) -> DomainError:
    """Ошибку части от БЗО — на поля формы tender: статья части, её позиции
    (``items[k]`` ЗЗ → ``items[i]`` заявки) или плановая сумма доставки/СМР."""
    tag = {"part": str(plan.part.pk), "kind": plan.kind, "article_id": plan.article_id}

    def where(name: str) -> str:
        if name == "article_id":
            return plan.article_field
        if name == "items" or name.startswith("items["):
            if plan.kind != PartKind.GOODS:
                return plan.items_field
            if name.startswith("items[") and "]" in name:
                head, _, rest = name[len("items["):].partition("]")
                if head.isdigit() and int(head) < len(plan.indexes):
                    return f"items[{plan.indexes[int(head)]}]{rest}"
            return "items"
        return name

    fields = [{**entry, "field": where(entry.get("field", "")), **tag}
              for entry in exc.fields]
    if not fields:
        fields = [{"field": "parts", "message": exc.message, **tag}]
    out = DomainError(exc.code, exc.message, fields=fields, status=exc.status)
    out.details = tag
    return out


# ── отправка ────────────────────────────────────────────────────────────

@transaction.atomic
def submit(ctx: crud.Ctx, request_id, *, expected_version: int | None) -> TenderRequest:
    req = _own(ctx, request_id, expected_version, "отправить", crud.EDITABLE)
    items = list(req.items.order_by("line_no"))
    _check_required(req, items)
    role = crud._role_for(ctx, req.initiator_role)
    crud._check_project(ctx, role, req.project_id)
    plans = _plans(req, items)
    _check_groups(role, plans)
    send, dropped = _match(req, plans)
    if not send:
        raise DomainError("E-STS-01", f"В заявке {req.number} нет частей для отправки: все "
                                      f"они уже на согласовании или утверждены.", status=409)
    actor = tender_actor(ctx)
    dropped_info = [{"bpp_number": part.bpp_number, "kind": part.kind,
                     "article_id": str(part.article_id)} for part in dropped]
    if dropped:
        with acting_on(req.pk):
            bpp.cancel_requests_from_tender([str(p.bpp_request_id) for p in dropped],
                                            actor=actor, comment=DROP_REASON)
        for part in dropped:
            part.delete()
    for plan in send:
        if plan.part is None:
            plan.part = TenderRequestPart(request=req, kind=plan.kind,
                                          article_id=plan.article_id,
                                          purchase_type=plan.purchase_type,
                                          created_by=ctx.user_id, updated_by=ctx.user_id)
    by_key = {str(plan.part.pk): plan for plan in send}
    payload = bpp.TenderRequestSubmit(
        actor=actor, initiator_role=role, project_id=str(req.project_id),
        tender_number=req.number, justification=req.justification.strip(),
        need_date=req.need_date,
        parts=[bpp.TenderPartIn(
            key=str(plan.part.pk),
            bpp_request_id=str(plan.part.bpp_request_id) if plan.part.bpp_request_id else None,
            article_id=plan.article_id, purchase_type=plan.purchase_type,
            items=[bpp.TenderItemIn(**line) for line in plan.lines]) for plan in send])
    try:
        with acting_on(req.pk):
            refs = bpp.submit_request_from_tender(payload)
    except DomainError as exc:
        plan = by_key.get((getattr(exc, "details", None) or {}).get("part"))
        if plan is None:
            raise
        raise _for_part(exc, plan) from exc
    for ref in refs:
        plan = by_key[ref.key]
        part = plan.part
        part.bpp_request_id, part.bpp_number, part.bpp_status = (
            ref.bpp_request_id, ref.number, ref.status)
        part.purchase_type, part.updated_by = plan.purchase_type, ctx.user_id
        part.save()
        # Доставка и СМР строками заявки не хранятся — связывать нечего.
        linked = zip(plan.items, ref.items, strict=True) if plan.kind == PartKind.GOODS else ()
        for item, item_id in linked:
            item.part, item.bpp_request_item_id, item.updated_by = part, item_id, ctx.user_id
            item.save(update_fields=["part", "bpp_request_item_id", "updated_by",
                                     "updated_at"])
    req.refresh_from_db()
    before = req.status
    req.status = rolled_status(active_parts(req).values_list("bpp_status", flat=True))
    req.rework_comment = req.status_comment = ""
    req.version += 1
    req.updated_by = ctx.user_id
    req.save(update_fields=["status", "rework_comment", "status_comment", "version",
                            "updated_by", "updated_at"])
    audit.record(req, "submitted", actor_id=ctx.user_id, changes={
        "status": [before, req.status], "project_id": str(req.project_id),
        "initiator_role": role, "sent": [ref.number for ref in refs],
        "dropped": dropped_info,
        "parts": {str(plan.part.pk): plan.fingerprint() for plan in plans},
    })
    return req


# ── отзыв, отмена, исключение части ─────────────────────────────────────

def _finish(req: TenderRequest, ctx: crud.Ctx, status: str, action: str, *,
            changes: dict | None = None, **extra) -> TenderRequest:
    """Итог действия пользователя: статус и поля заявки, версия +1 и ОДНА
    строка журнала (слушатель на время действия заявку не трогает,
    ``status.acting_on``)."""
    req.refresh_from_db()
    before = req.status
    req.status = status
    for name, value in extra.items():
        setattr(req, name, value)
    req.version += 1
    req.updated_by = ctx.user_id
    req.save()
    audit.record(req, action, actor_id=ctx.user_id,
                 changes={"status": [before, status], **(changes or {})},
                 comment=extra.get("status_comment", ""))
    return req


@transaction.atomic
def withdraw(ctx: crud.Ctx, request_id, *, expected_version: int | None) -> TenderRequest:
    """Отозвать ЗЗ «На согласовании» (без решений — иначе E-STS-01 от БЗО);
    утверждённые части остаются утверждёнными, заявка — «Черновик»."""
    req = _own(ctx, request_id, expected_version, "отозвать",
               (TenderRequestStatus.IN_APPROVAL,))
    ids = [str(p.bpp_request_id) for p in active_parts(req)
           if p.bpp_request_id and p.bpp_status == "in_approval"]
    if ids:
        with acting_on(req.pk):
            bpp.withdraw_requests_from_tender(ids, actor=tender_actor(ctx))
    return _finish(req, ctx, rolled_status(active_parts(req).values_list("bpp_status",
                                                                          flat=True)),
                   "withdrawn")


@transaction.atomic
def cancel(ctx: crud.Ctx, request_id, *, expected_version: int | None,
           comment: str) -> TenderRequest:
    """Отменить заявку: ЗЗ «Черновик»/«На доработке» отменяются, утверждённые
    закрываются остатком (резерв снимается), отклонённые остаются как есть.
    «На согласовании» — сначала отозвать (409 E-STS-01)."""
    req = _own(ctx, request_id, expected_version, "отменить",
               (*crud.EDITABLE, TenderRequestStatus.APPROVED, TenderRequestStatus.REJECTED))
    comment = (comment or "").strip()
    if len(comment) < COMMENT_MIN:
        raise crud._bad("comment", f"опишите причину: комментарий не короче {COMMENT_MIN} "
                                   f"символов")
    ids = [str(p.bpp_request_id) for p in active_parts(req) if p.bpp_request_id]
    if ids:
        with acting_on(req.pk):
            bpp.cancel_requests_from_tender(ids, actor=tender_actor(ctx), comment=comment)
    return _finish(req, ctx, TenderRequestStatus.CANCELLED, "cancelled",
                   status_comment=comment)


@transaction.atomic
def exclude_part(ctx: crud.Ctx, request_id, part_id, *,
                 expected_version: int | None) -> TenderRequest:
    """«Исключить часть» (T-08): только отклонённую. Её позиции уходят из
    заявки (ЗЗ в БЗО остаётся «Отклонена»), признак доставки/СМР снимается,
    статус пересчитывается по остальным частям."""
    req = _own(ctx, request_id, expected_version, "исключить часть", ROLLED)
    try:
        key = uuid.UUID(str(part_id))
    except (ValueError, AttributeError, TypeError):
        key = None  # невозможный ключ — как несуществующая часть
    part = req.parts.filter(pk=key, excluded_at__isnull=True).first() if key else None
    if part is None:
        raise DomainError("E-NOT-FOUND", "Часть заявки не найдена.", status=404)
    if not excludable_parts(req).filter(pk=part.pk).exists():
        raise DomainError(
            "E-STS-01", f"Исключить можно только отклонённую часть; ЗЗ {part.bpp_number} — "
                        f"не отклонена.", status=409)
    part.excluded_at, part.updated_by = timezone.now(), ctx.user_id
    part.save(update_fields=["excluded_at", "updated_by", "updated_at"])
    removed = list(req.items.filter(part=part).values_list("name", flat=True))
    req.items.filter(part=part).delete()
    for line_no, item in enumerate(req.items.order_by("line_no"), start=1):
        if item.line_no != line_no:
            item.line_no = line_no
            item.save(update_fields=["line_no", "updated_at"])
    flags = {}
    if part.kind == PartKind.DELIVERY:
        flags["needs_delivery"] = False
    if part.kind == PartKind.WORKS:
        flags["needs_works"] = False
    return _finish(req, ctx, rolled_status(active_parts(req).values_list("bpp_status",
                                                                          flat=True)),
                   "part_excluded", changes={"part": str(part.pk),
                                             "bpp_number": part.bpp_number,
                                             "items": removed}, **flags)
