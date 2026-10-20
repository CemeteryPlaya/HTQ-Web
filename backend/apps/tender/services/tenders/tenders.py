"""Тендер: черновик, схема оплаты, публикация, продление, отмена (T2.1; план
этапов 0–2, §4.2).

Права — узел ``tender.tenders`` (создать / править); «все тендеры» —
``tender.tenders.all`` (``EXPLICIT_ONLY``). Видит тендер автор и держатель
``*.all``; действует только автор. Тендер объявляется по утверждённой заявке,
которую закупщик видит; у заявки не больше одного активного тендера.

Статус заявки здесь меняется в двух местах, оба — в транзакции тендера:
публикация «Утверждена» → «В тендере», отмена «В тендере» → «Утверждена»
(ТЗ: заявку можно объявить заново). Писем в этапе 2 нет: публикация лишь
выпускает ссылки (почта — этап 4).
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from types import SimpleNamespace

from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.utils import timezone

from apps.access import interface as access
from apps.tender.models import (
    ACTIVE_TENDER_STATUSES,
    DeviceBinding,
    Invitation,
    InvitationStatus,
    PaymentScheme,
    Tender,
    TenderRequest,
    TenderRequestStatus,
    TenderStatus,
)
from apps.tender.services.core import audit
from apps.tender.services.core.errors import check_version
from apps.tender.services.core.numbering import TENDER_PREFIX, next_number
from apps.users import interface as users
from htqweb.errors import DomainError

from . import schemes, tokens
from .ctx import Ctx, bad, deny

OBJECT_TYPE = "tender.tender"
NODE, NODE_ALL = "tender.tenders", "tender.tenders.all"
QUALITY_NODE = "tender.award.quality"
REQUESTS_ALL = "tender.requests.all"
REASON_MIN, TEXT_MAX = 10, 2000
_CURRENCY = re.compile(r"^[A-Z]{3}$")

#: Проверяющего качество можно сменить до утверждения выбора (T-11).
REVIEWER_EDITABLE = (TenderStatus.DRAFT, TenderStatus.INTAKE, TenderStatus.OPENED,
                     TenderStatus.REWORK)
CANCELLABLE = (TenderStatus.DRAFT, TenderStatus.INTAKE, TenderStatus.OPENED,
               TenderStatus.REWORK)
#: Приглашают и отзывают до публикации (черновик) и во время приёма.
INVITABLE = (TenderStatus.DRAFT, TenderStatus.INTAKE)
#: Приглашение закрыто — действий у него нет: отозвано, поставщик отказался,
#: итог подведён, срок истёк.
CLOSED_INVITATIONS = (InvitationStatus.REVOKED, InvitationStatus.DECLINED,
                      InvitationStatus.AWARDED, InvitationStatus.NOT_AWARDED,
                      InvitationStatus.EXPIRED)
#: Ссылка дошла до поставщика: всё, кроме «Создано», ошибки доставки и отзыва.
_DELIVERED = tuple(s for s in InvitationStatus
                   if s not in (InvitationStatus.CREATED, InvitationStatus.DELIVERY_ERROR,
                                InvitationStatus.REVOKED))
#: Предложение подано (и дальше по итогам выбора).
_SUBMITTED = (InvitationStatus.SUBMITTED, InvitationStatus.AWARDED,
              InvitationStatus.NOT_AWARDED)


# ── ошибки ──────────────────────────────────────────────────────────────

def not_found() -> DomainError:
    return DomainError("E-NOT-FOUND", "Тендер не найден.", status=404)


def state_error(action: str, tender: Tender) -> DomainError:
    return DomainError(
        "E-STS-01",
        f"Нельзя {action} тендер {tender.number} в статусе „{tender.get_status_display()}“.",
        status=409)


# ── видимость и права ───────────────────────────────────────────────────

def can_view(ctx: Ctx, tender: Tender) -> bool:
    return tender.author_id == ctx.user_id or ctx.can(NODE_ALL, "view")


def _key(value) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None


def get_visible(ctx: Ctx, tender_id, *, lock: bool = False) -> Tender:
    ctx.require(NODE, "view", "Недостаточно прав на тендеры.")
    key = _key(tender_id)
    rows = Tender.objects.select_for_update() if lock else Tender.objects
    tender = rows.filter(pk=key).first() if key else None
    if tender is None or not can_view(ctx, tender):
        raise not_found()
    return tender


def get_own(ctx: Ctx, tender_id, action: str) -> Tender:
    """Тендер под блокировкой — для действия автора (``edit`` на узле)."""
    ctx.require(NODE, "edit", "Недостаточно прав на тендеры.")
    tender = get_visible(ctx, tender_id, lock=True)
    if tender.author_id != ctx.user_id:
        raise deny(f"{action} тендер {tender.number} может только его автор.")
    return tender


def intake_open(tender: Tender) -> bool:
    return (tender.status == TenderStatus.INTAKE and tender.deadline_at is not None
            and tender.deadline_at > timezone.now())


def everyone_answered(tender: Tender) -> bool:
    """Каждое живое приглашение подало предложение или отказалось — тогда
    вскрыть можно и до срока (S5-02): ни у кого не отнимут обещанное время."""
    live = tender.invitations.filter(revoked_at__isnull=True)
    return live.exists() and not live.exclude(
        status__in=[InvitationStatus.SUBMITTED, InvitationStatus.DECLINED]).exists()


def may_open(tender: Tender) -> bool:
    """Вскрыть можно на приёме — после срока или когда ответили все."""
    return tender.status == TenderStatus.INTAKE and (
        not intake_open(tender) or everyone_answered(tender))


def allowed_actions(ctx: Ctx, tender: Tender) -> list[str]:
    if tender.author_id != ctx.user_id or not ctx.can(NODE, "edit"):
        return []
    if tender.status == TenderStatus.DRAFT:
        actions = ["edit", "publish", "cancel", "invite"]
    elif tender.status == TenderStatus.INTAKE:
        actions = ["extend", "cancel", *(["invite"] if intake_open(tender) else []),
                   *(["open"] if may_open(tender) else [])]
    elif tender.status in (TenderStatus.OPENED, TenderStatus.REWORK):
        # Выбор поставщиков (этап 5): сохранить и — если выбор есть — отправить.
        actions = ["cancel", "award", *(["award_submit"] if tender.awards.exists() else [])]
    elif tender.status in CANCELLABLE:
        actions = ["cancel"]
    else:
        actions = []
    if tender.status in REVIEWER_EDITABLE:
        actions.append("reviewer")      # сменить проверяющего качества (до утверждения)
    return actions


def invitation_actions(ctx: Ctx, tender: Tender, row: Invitation) -> list[str]:
    """Что автор может сделать с приглашением сейчас. Один список — и для
    кнопок карточки (``allowed_actions`` приглашения), и для проверки самих
    действий в ``invitations.py``: кнопка и сервер не расходятся.

    Отзыв — в черновике и на приёме; перевыпуск ссылки и сброс устройства —
    только пока приём идёт (после срока поставщик уже ничего не подаст)."""
    if tender.author_id != ctx.user_id or not ctx.can(NODE, "edit"):
        return []
    if row.revoked_at is not None or row.status in CLOSED_INVITATIONS:
        return []
    actions = ["revoke"] if tender.status in INVITABLE else []
    if intake_open(tender):
        actions += ["reissue", "reset_device"]
    return actions


# ── проверки полей ──────────────────────────────────────────────────────

def _deadline(value, *, field_name: str = "deadline_at") -> datetime:
    if value is None:
        raise bad(field_name, "укажите срок приёма предложений")
    if timezone.is_naive(value):
        value = timezone.make_aware(value)
    if value <= timezone.now():
        raise bad(field_name, "срок приёма предложений — в будущем")
    return value


def _currency(value: str) -> str:
    code = (value or "").strip().upper()
    if not _CURRENCY.match(code):
        raise bad("currency_code", "валюта — трёхбуквенный код ISO 4217")
    return code


def _reviewer(ctx: Ctx, user_id: int | None) -> int | None:
    """Проверяющий качество — действующий пользователь с ролью ``tender-quality``
    (узел ``tender.award.quality`` с признаком ``edit``) в этой компании."""
    if user_id is None:
        return None
    briefs = users.get_users_brief([user_id])
    holder = SimpleNamespace(id=int(user_id), is_superuser=False, email=None)
    if (not briefs or not briefs[0]["is_active"]
            or "edit" not in access.flags_for(holder, QUALITY_NODE, ctx.company)):
        raise bad("quality_reviewer_user_id",
                  "проверяющий — пользователь с ролью «Тендеры: Проверка качества»")
    return int(user_id)


def _request_visible(ctx: Ctx, req: TenderRequest) -> bool:
    return req.author_id == ctx.user_id or ctx.can(REQUESTS_ALL, "view")


def _touch(obj, actor_id: int) -> None:
    obj.version += 1
    obj.updated_by = actor_id
    obj.save()


def _set_request_status(req: TenderRequest, status: str, actor_id: int, action: str,
                        tender: Tender) -> None:
    before = req.status
    req.status = status
    _touch(req, actor_id)
    audit.record(req, action, actor_id=actor_id,
                 changes={"status": [before, status], "tender": tender.number})


# ── черновик ────────────────────────────────────────────────────────────

@transaction.atomic
def create(ctx: Ctx, data: dict) -> Tender:
    ctx.require(NODE, "create", "Недостаточно прав, чтобы объявлять тендеры.")
    key = _key(data.get("request_id"))
    req = TenderRequest.objects.select_for_update().filter(pk=key).first() if key else None
    if req is None or not _request_visible(ctx, req):
        raise DomainError("E-NOT-FOUND", "Заявка не найдена.", status=404,
                          fields=[{"field": "request_id", "message": "Заявка не найдена"}])
    if req.status != TenderRequestStatus.APPROVED:
        raise DomainError(
            "E-STS-01",
            f"Тендер объявляется только по утверждённой заявке; заявка {req.number} — "
            f"„{req.get_status_display()}“.", status=409)
    active = req.tenders.filter(status__in=ACTIVE_TENDER_STATUSES).first()
    if active is not None:
        raise _second_active(req, active.number)
    tender = Tender(
        number=next_number(TENDER_PREFIX), request=req, author_id=ctx.user_id,
        deadline_at=_deadline(data["deadline_at"]) if data.get("deadline_at") else None,
        currency_code=_currency(data.get("currency_code") or "KZT"),
        delivery_terms=(data.get("delivery_terms") or "").strip()[:TEXT_MAX],
        quality_reviewer_user_id=_reviewer(ctx, data.get("quality_reviewer_user_id")),
        created_by=ctx.user_id, updated_by=ctx.user_id)
    try:
        with transaction.atomic():
            tender.save()
    except IntegrityError:
        # Параллельное «Объявить тендер» по той же заявке успело первым.
        raise _second_active(req, "") from None
    audit.record(tender, "created", actor_id=ctx.user_id,
                 changes={"request": req.number, "deadline_at": _iso(tender.deadline_at)})
    return tender


def _second_active(req: TenderRequest, number: str) -> DomainError:
    which = f" ({number})" if number else ""
    return DomainError(
        "E-TND-01", f"По заявке {req.number} уже идёт тендер{which}. Отмените его или "
                    f"дождитесь завершения.", status=409)


_DRAFT_FIELDS = ("deadline_at", "currency_code", "delivery_terms")


@transaction.atomic
def update(ctx: Ctx, tender_id, *, expected_version: int | None, data: dict) -> Tender:
    tender = get_own(ctx, tender_id, "Править")
    draft_only = [name for name in _DRAFT_FIELDS if name in data]
    if draft_only and tender.status != TenderStatus.DRAFT:
        raise state_error("править", tender)
    if "quality_reviewer_user_id" in data and tender.status not in REVIEWER_EDITABLE:
        raise state_error("сменить проверяющего у", tender)
    check_version(tender, expected_version)
    changes = {}
    if "deadline_at" in data:
        value = _deadline(data["deadline_at"]) if data["deadline_at"] else None
        changes["deadline_at"] = [_iso(tender.deadline_at), _iso(value)]
        tender.deadline_at = value
    if "currency_code" in data:
        value = _currency(data["currency_code"] or "")
        changes["currency_code"] = [tender.currency_code, value]
        tender.currency_code = value
    if "delivery_terms" in data:
        value = (data["delivery_terms"] or "").strip()[:TEXT_MAX]
        changes["delivery_terms"] = [tender.delivery_terms, value]
        tender.delivery_terms = value
    if "quality_reviewer_user_id" in data:
        value = _reviewer(ctx, data["quality_reviewer_user_id"])
        changes["quality_reviewer_user_id"] = [tender.quality_reviewer_user_id, value]
        tender.quality_reviewer_user_id = value
    _touch(tender, ctx.user_id)
    audit.record(tender, "updated", actor_id=ctx.user_id, changes=changes)
    return tender


@transaction.atomic
def set_payment_scheme(ctx: Ctx, tender_id, *, kind: str, advance_pct=None,
                       postpay_days=None) -> Tender:
    """Желаемая схема — из шаблона; только в черновике. Без ``version``
    (контракт фронта): схема — отдельная строка, шапку тендера не меняет."""
    tender = get_own(ctx, tender_id, "Править")
    if tender.status != TenderStatus.DRAFT:
        raise state_error("сменить схему оплаты у", tender)
    scheme = schemes.replace(tender, kind, advance_pct=advance_pct,
                             postpay_days=postpay_days, actor_id=ctx.user_id)
    audit.record(tender, "payment_scheme", actor_id=ctx.user_id, changes=schemes.out(scheme))
    return tender


# ── публикация, продление, отмена ───────────────────────────────────────

@transaction.atomic
def publish(ctx: Ctx, tender_id, *, expected_version: int | None) -> list[dict]:
    """Черновик → «Приём предложений»: всем созданным приглашениям — ссылки.
    Ответ — ``[{invitation_id, link}]``: сырые токены не хранятся, второй раз
    их не получить (перевыпуск даёт новую ссылку)."""
    tender = get_own(ctx, tender_id, "Опубликовать")
    if tender.status != TenderStatus.DRAFT:
        raise state_error("опубликовать", tender)
    check_version(tender, expected_version)
    live = list(tender.invitations.filter(revoked_at__isnull=True))
    missing = []
    if not live:
        missing.append({"field": "invitations", "message": "Пригласите хотя бы одного участника"})
    if tender.deadline_at is None or tender.deadline_at <= timezone.now():
        missing.append({"field": "deadline_at", "message": "Срок приёма — в будущем"})
    if not PaymentScheme.objects.filter(tender=tender).exists():
        missing.append({"field": "payment_scheme", "message": "Выберите схему оплаты"})
    if missing:
        raise DomainError("E-TND-04", f"Тендер {tender.number} не готов к публикации: "
                                      + "; ".join(m["message"].lower() for m in missing) + ".",
                          fields=missing)
    req = TenderRequest.objects.select_for_update().get(pk=tender.request_id)
    if req.status != TenderRequestStatus.APPROVED:
        raise DomainError(
            "E-STS-01", f"Заявка {req.number} больше не утверждена („{req.get_status_display()}“) "
                        f"— тендер по ней не публикуется.", status=409)
    _set_request_status(req, TenderRequestStatus.IN_TENDER, ctx.user_id, "in_tender", tender)
    now = timezone.now()
    links = []
    for invitation in live:
        if invitation.status != InvitationStatus.CREATED:
            continue
        links.append({"invitation_id": str(invitation.pk),
                      "link": send_link(ctx, invitation, now)})
    tender.status = TenderStatus.INTAKE
    _touch(tender, ctx.user_id)
    audit.record(tender, "published", actor_id=ctx.user_id,
                 changes={"invitations": len(links), "deadline_at": _iso(tender.deadline_at)})
    return links


def send_link(ctx: Ctx, invitation: Invitation, now) -> str:
    """Выпустить ссылку приглашению: хэш — в строку, сырой токен — наружу.
    Писем нет (этап 4): «отправлено» = ссылка выдана закупщику."""
    token, digest = tokens.issue()
    invitation.token_hash = digest
    invitation.status = InvitationStatus.SENT
    invitation.sent_at = now
    invitation.updated_by = ctx.user_id
    invitation.save(update_fields=["token_hash", "status", "sent_at", "updated_by",
                                   "updated_at"])
    return tokens.link(ctx.company, token)


@transaction.atomic
def extend(ctx: Ctx, tender_id, *, expected_version: int | None, deadline_at) -> Tender:
    tender = get_own(ctx, tender_id, "Продлить")
    if tender.status != TenderStatus.INTAKE:
        raise state_error("продлить", tender)
    check_version(tender, expected_version)
    value = _deadline(deadline_at)
    if tender.deadline_at and value <= tender.deadline_at:
        raise bad("deadline_at", "новый срок — позже текущего")
    before = tender.deadline_at
    tender.deadline_at = value
    _touch(tender, ctx.user_id)
    audit.record(tender, "extended", actor_id=ctx.user_id,
                 changes={"deadline_at": [_iso(before), _iso(value)]})
    return tender


@transaction.atomic
def cancel(ctx: Ctx, tender_id, *, expected_version: int | None, reason: str) -> Tender:
    """Отмена с причиной: все приглашения отзываются (ссылки перестают
    работать), заявка «В тендере» возвращается в «Утверждена»."""
    tender = get_own(ctx, tender_id, "Отменить")
    if tender.status not in CANCELLABLE:
        raise state_error("отменить", tender)
    check_version(tender, expected_version)
    reason = (reason or "").strip()
    if len(reason) < REASON_MIN:
        raise bad("reason", f"причина отмены — не короче {REASON_MIN} символов")
    now = timezone.now()
    revoked = revoke_all(tender, now=now, actor_id=ctx.user_id)
    tender.status = TenderStatus.CANCELLED
    tender.cancel_reason = reason[:TEXT_MAX]
    _touch(tender, ctx.user_id)
    release_request(tender, ctx.user_id)
    audit.record(tender, "cancelled", actor_id=ctx.user_id, comment=tender.cancel_reason,
                 changes={"invitations_revoked": revoked})
    return tender


def revoke_all(tender: Tender, *, now, actor_id: int) -> int:
    live = tender.invitations.filter(revoked_at__isnull=True)
    ids = list(live.values_list("pk", flat=True))
    live.update(status=InvitationStatus.REVOKED, revoked_at=now, updated_by=actor_id,
                updated_at=now)
    DeviceBinding.objects.filter(invitation_id__in=ids, revoked_at__isnull=True).update(
        revoked_at=now, updated_by=actor_id, updated_at=now)
    return len(ids)


def release_request(tender: Tender, actor_id: int) -> None:
    """Отмена и «Не состоялся» возвращают заявку в «Утверждена» (ТЗ), если
    тендер успел её занять (опубликован)."""
    req = TenderRequest.objects.select_for_update().get(pk=tender.request_id)
    if req.status == TenderRequestStatus.IN_TENDER:
        _set_request_status(req, TenderRequestStatus.APPROVED, actor_id, "released", tender)


# ── чтение ──────────────────────────────────────────────────────────────

def _iso(value) -> str | None:
    return value.isoformat() if value else None


def counters_of(rows) -> dict:
    """Счётчики TND-013 из статусов приглашений (отозванные не считаются)."""
    live = [r for r in rows if r.revoked_at is None]
    return {
        "sent": sum(1 for r in live if r.sent_at and r.status in _DELIVERED),
        "opened": sum(1 for r in live if r.first_opened_at),
        "submitted": sum(1 for r in live if r.status in _SUBMITTED),
    }


_COUNTER_FILTERS = {
    "sent": Q(invitations__revoked_at__isnull=True, invitations__sent_at__isnull=False,
              invitations__status__in=_DELIVERED),
    "opened": Q(invitations__revoked_at__isnull=True,
                invitations__first_opened_at__isnull=False),
    "submitted": Q(invitations__revoked_at__isnull=True, invitations__status__in=_SUBMITTED),
}


def invitation_out(row: Invitation, actions: list[str]) -> dict:
    """Приглашение наружу — белым списком: ни токена, ни хэша (T-26).
    ``actions`` — ``invitation_actions`` для того, кто смотрит."""
    return {"id": str(row.pk), "counterparty_id": str(row.counterparty_id)
            if row.counterparty_id else None,
            "prospect_id": str(row.prospect_id) if row.prospect_id else None,
            "name": row.name, "email": row.email, "status": row.status,
            "sent_at": _iso(row.sent_at), "first_opened_at": _iso(row.first_opened_at),
            "revoked_at": _iso(row.revoked_at), "max_devices": row.max_devices,
            "allowed_actions": actions}


def card(ctx: Ctx, tender: Tender) -> dict:
    invitations = list(tender.invitations.order_by("created_at"))
    reviewer_name = None
    if tender.quality_reviewer_user_id:
        briefs = users.get_users_brief([tender.quality_reviewer_user_id])
        reviewer_name = briefs[0]["full_name"] if briefs else None
    req = tender.request
    return {
        "id": str(tender.pk), "number": tender.number, "status": tender.status,
        "status_display": tender.get_status_display(), "request_id": str(req.pk),
        "request_number": req.number, "request_status": req.status,
        "author_id": tender.author_id, "deadline_at": _iso(tender.deadline_at),
        "currency_code": tender.currency_code, "delivery_terms": tender.delivery_terms,
        "quality_reviewer_user_id": tender.quality_reviewer_user_id,
        "quality_reviewer_name": reviewer_name, "cancel_reason": tender.cancel_reason,
        "opened_at": _iso(tender.opened_at), "round": tender.round, "version": tender.version,
        "created_at": _iso(tender.created_at),
        "allowed_actions": allowed_actions(ctx, tender),
        "payment_scheme": schemes.out(PaymentScheme.objects.filter(tender=tender).first()),
        "counters": counters_of(invitations),
        "invitations": [invitation_out(row, invitation_actions(ctx, tender, row))
                        for row in invitations],
    }


def registry(ctx: Ctx, *, statuses: list[str], request_id: str | None, query: str,
             page: int, page_size: int) -> dict:
    ctx.require(NODE, "view", "Недостаточно прав на тендеры.")
    rows = Tender.objects.select_related("request")
    if not ctx.can(NODE_ALL, "view"):
        rows = rows.filter(author_id=ctx.user_id)
    if statuses:
        rows = rows.filter(status__in=statuses)
    if request_id:
        key = _key(request_id)
        if key is None:
            raise bad("request_id", "неверный ключ заявки")
        rows = rows.filter(request_id=key)
    if query:
        rows = rows.filter(Q(number__icontains=query) | Q(request__number__icontains=query))
    total = rows.count()
    start = (page - 1) * page_size
    found = list(rows.annotate(**{f"n_{name}": Count("invitations", filter=cond)
                                  for name, cond in _COUNTER_FILTERS.items()})
                 .order_by("-created_at", "-number")[start:start + page_size])
    return {
        "results": [{
            "id": str(t.pk), "number": t.number, "status": t.status,
            "status_display": t.get_status_display(), "request_id": str(t.request_id),
            "request_number": t.request.number, "deadline_at": _iso(t.deadline_at),
            "author_id": t.author_id, "created_at": _iso(t.created_at),
            "counters": {"sent": t.n_sent, "opened": t.n_opened, "submitted": t.n_submitted},
        } for t in found],
        "total": total, "page": page, "page_size": page_size,
    }


# ── регистрация ─────────────────────────────────────────────────────────

def _history_can_view(request, object_id: str) -> bool:
    ctx = Ctx.from_request(request)
    key = _key(object_id)
    tender = Tender.objects.filter(pk=key).first() if key else None
    return tender is not None and ctx.can(NODE, "view") and can_view(ctx, tender)


def register() -> None:
    """Журнал тендера читается только тем, кто видит сам тендер (T-28).
    Зовётся из ``TenderConfig.ready()``."""
    audit.register_history_access(OBJECT_TYPE, _history_can_view)
