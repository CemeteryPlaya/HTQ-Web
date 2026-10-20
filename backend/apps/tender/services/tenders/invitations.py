"""Приглашения участников и их ссылки (T2.2; план этапов 0–2, §4.2; мастер-план
T-21, T-26).

Участник — контрагент БЗО (только «Активен» по ``bpp.counterparty_brief``,
иначе 422 ``E-TND-02``; почта — из выбранного контакта или карточки) либо
потенциальный поставщик с почтой. Приглашают в черновике и во время приёма
до срока; приглашённый после публикации получает ссылку сразу. Отзыв,
перевыпуск (старый хэш заменяется — старая ссылка перестаёт работать) и сброс
устройства — у автора тендера.

В журнал пишутся ключ приглашения и адрес — никогда токен или его хэш.
"""

from __future__ import annotations

import uuid

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.bpp import interface as bpp
from apps.tender.models import (
    DeviceBinding,
    Invitation,
    InvitationStatus,
    SupplierContact,
    SupplierProspect,
    Tender,
    TenderStatus,
)
from apps.tender.services.core import audit
from apps.tender.services.portal import access as portal
from htqweb.errors import DomainError

from . import tenders, tokens
from .ctx import Ctx, bad

#: До публикации приглашают в черновике, после — пока идёт приём.
INVITABLE = tenders.INVITABLE


def _refuse(field_name: str, text: str) -> DomainError:
    return bad(field_name, text, code="E-TND-02")


def _key(value) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None


def list_for(ctx: Ctx, tender_id) -> list[dict]:
    tender = tenders.get_visible(ctx, tender_id)
    return [_out(ctx, tender, row) for row in tender.invitations.order_by("created_at")]


def _party_from_counterparty(data: dict) -> dict:
    key = _key(data.get("counterparty_id"))
    card = bpp.counterparty_brief([str(key)]).get(str(key)) if key else None
    if card is None:
        raise _refuse("counterparty_id", "контрагент не найден")
    if card["status"] != "active":
        raise _refuse("counterparty_id",
                      f"контрагент «{card['name']}» не активен — пригласить его нельзя")
    email = (card.get("email") or "").strip().lower()
    if data.get("contact_id"):
        contact = SupplierContact.objects.filter(pk=_key(data["contact_id"])).first()
        if contact is None or contact.counterparty_id != key or not contact.is_active:
            raise _refuse("contact_id", "контакт не найден у этого контрагента")
        email = contact.email
    if not email:
        raise _refuse("contact_id", f"у контрагента «{card['name']}» нет почты — выберите "
                                    f"или заведите контакт")
    return {"counterparty_id": key, "prospect": None, "email": email,
            "name": card.get("short_name") or card["name"]}


def _party_from_prospect(data: dict) -> dict:
    prospect = SupplierProspect.objects.filter(pk=_key(data.get("prospect_id"))).first()
    if prospect is None:
        raise _refuse("prospect_id", "потенциальный поставщик не найден")
    if not prospect.email:
        raise _refuse("prospect_id", f"у «{prospect.name}» нет почты")
    return {"counterparty_id": None, "prospect": prospect, "email": prospect.email.lower(),
            "name": prospect.name}


@transaction.atomic
def add(ctx: Ctx, tender_id, data: dict) -> dict:
    """Пригласить участника. Ответ — приглашение; после публикации — ещё и
    ``link`` (единственный раз, когда его видно)."""
    tender = tenders.get_own(ctx, tender_id, "Приглашать в")
    if tender.status not in INVITABLE or (tender.status == TenderStatus.INTAKE
                                          and not tenders.intake_open(tender)):
        raise tenders.state_error("приглашать участников в", tender)
    has_cp, has_prospect = bool(data.get("counterparty_id")), bool(data.get("prospect_id"))
    if has_cp == has_prospect:
        raise bad("counterparty_id", "выберите контрагента или потенциального поставщика")
    party = _party_from_counterparty(data) if has_cp else _party_from_prospect(data)
    live = tender.invitations.filter(revoked_at__isnull=True)
    duplicate = (live.filter(email=party["email"]).exists()
                 or (party["counterparty_id"]
                     and live.filter(counterparty_id=party["counterparty_id"]).exists())
                 or (party["prospect"] and live.filter(prospect=party["prospect"]).exists()))
    if duplicate:
        raise _refuse("counterparty_id" if has_cp else "prospect_id",
                      f"«{party['name']}» уже приглашён в тендер {tender.number}")
    invitation = Invitation(tender=tender, created_by=ctx.user_id, updated_by=ctx.user_id,
                            **party)
    try:
        with transaction.atomic():
            invitation.save()
    except IntegrityError:
        raise _refuse("counterparty_id" if has_cp else "prospect_id",
                      f"«{party['name']}» уже приглашён в тендер {tender.number}") from None
    out = None
    if tender.status == TenderStatus.INTAKE:
        out = tenders.send_link(ctx, invitation, timezone.now())
    audit.record(tender, "invited", actor_id=ctx.user_id,
                 changes={"invitation": str(invitation.pk), "email": invitation.email,
                          "name": invitation.name})
    body = _out(ctx, tender, invitation)
    if out is not None:
        body["link"] = out
    return body


def _own_invitation(ctx: Ctx, tender_id, invitation_id, action: str
                    ) -> tuple[Tender, Invitation]:
    tender = tenders.get_own(ctx, tender_id, action)
    key = _key(invitation_id)
    invitation = (Invitation.objects.select_for_update()
                  .filter(pk=key, tender=tender).first() if key else None)
    if invitation is None:
        raise DomainError("E-NOT-FOUND", "Приглашение не найдено.", status=404)
    return tender, invitation


def _revoke_devices(invitation: Invitation, *, now, actor_id: int) -> int:
    return DeviceBinding.objects.filter(invitation=invitation, revoked_at__isnull=True).update(
        revoked_at=now, updated_by=actor_id, updated_at=now)


def _invitation_state_error(invitation: Invitation, action: str) -> DomainError:
    return DomainError(
        "E-STS-01", f"Нельзя {action} приглашение «{invitation.name}» в статусе "
                    f"„{invitation.get_status_display()}“.", status=409)


def _require_action(ctx: Ctx, tender: Tender, invitation: Invitation, action: str, *,
                    tender_text: str, invitation_text: str) -> None:
    """Действие — только из ``tenders.invitation_actions``: тот же список
    отдаёт карточка. Отказ называет причину — закрытое приглашение или
    статус и срок тендера."""
    if action in tenders.invitation_actions(ctx, tender, invitation):
        return
    if invitation.revoked_at is not None or invitation.status in tenders.CLOSED_INVITATIONS:
        raise _invitation_state_error(invitation, invitation_text)
    raise tenders.state_error(tender_text, tender)


def _out(ctx: Ctx, tender: Tender, invitation: Invitation) -> dict:
    return tenders.invitation_out(invitation, tenders.invitation_actions(ctx, tender, invitation))


@transaction.atomic
def revoke(ctx: Ctx, tender_id, invitation_id) -> dict:
    tender, invitation = _own_invitation(ctx, tender_id, invitation_id, "Отзывать в")
    _require_action(ctx, tender, invitation, "revoke",
                    tender_text="отзывать приглашения в", invitation_text="отозвать")
    now = timezone.now()
    invitation.status = InvitationStatus.REVOKED
    invitation.revoked_at = now
    invitation.updated_by = ctx.user_id
    invitation.save(update_fields=["status", "revoked_at", "updated_by", "updated_at"])
    _revoke_devices(invitation, now=now, actor_id=ctx.user_id)
    audit.record(tender, "invitation_revoked", actor_id=ctx.user_id,
                 changes={"invitation": str(invitation.pk), "email": invitation.email})
    return _out(ctx, tender, invitation)


@transaction.atomic
def reissue(ctx: Ctx, tender_id, invitation_id) -> dict:
    """Новая ссылка взамен старой: хэш заменяется, старая ссылка больше не
    находит приглашение. Привязанные устройства отвязываются — иначе
    чужое устройство с утёкшей ссылки занимало бы единственное место."""
    tender, invitation = _own_invitation(ctx, tender_id, invitation_id, "Перевыпускать в")
    _require_action(ctx, tender, invitation, "reissue",
                    tender_text="перевыпустить ссылку в", invitation_text="перевыпустить")
    now = timezone.now()
    token, digest = tokens.issue()
    invitation.token_hash = digest
    if invitation.status in (InvitationStatus.CREATED, InvitationStatus.DELIVERY_ERROR):
        invitation.status = InvitationStatus.SENT
        invitation.sent_at = now
    invitation.updated_by = ctx.user_id
    invitation.save(update_fields=["token_hash", "status", "sent_at", "updated_by",
                                   "updated_at"])
    devices = _revoke_devices(invitation, now=now, actor_id=ctx.user_id)
    if devices:
        portal.log_event(invitation, "device_reset",
                         meta={"by_user_id": ctx.user_id, "reason": "reissue",
                               "devices": devices})
    audit.record(tender, "invitation_reissued", actor_id=ctx.user_id,
                 changes={"invitation": str(invitation.pk), "devices_reset": devices})
    return {"link": tokens.link(ctx.company, token)}


@transaction.atomic
def reset_device(ctx: Ctx, tender_id, invitation_id) -> dict:
    tender, invitation = _own_invitation(ctx, tender_id, invitation_id, "Сбрасывать в")
    _require_action(ctx, tender, invitation, "reset_device",
                    tender_text="сбросить устройство в", invitation_text="сбросить устройство у")
    devices = _revoke_devices(invitation, now=timezone.now(), actor_id=ctx.user_id)
    # В журнал портала — и сброс без привязок: закупщик нажал, поставщик увидит.
    portal.log_event(invitation, "device_reset",
                     meta={"by_user_id": ctx.user_id, "reason": "reset", "devices": devices})
    audit.record(tender, "device_reset", actor_id=ctx.user_id,
                 changes={"invitation": str(invitation.pk), "devices_reset": devices})
    return _out(ctx, tender, invitation)


def events(ctx: Ctx, tender_id, invitation_id) -> list[dict]:
    """Журнал портала приглашения — закупщику, который видит тендер (свой или
    с ``tender.tenders.all``). Без токенов и секретов: их там нет."""
    tender = tenders.get_visible(ctx, tender_id)
    key = _key(invitation_id)
    invitation = tender.invitations.filter(pk=key).first() if key else None
    if invitation is None:
        raise DomainError("E-NOT-FOUND", "Приглашение не найдено.", status=404)
    return [{"id": str(row.pk), "kind": row.kind, "ip": row.ip, "user_agent": row.user_agent,
             "meta": row.meta, "created_at": row.created_at.isoformat()}
            for row in invitation.portal_events.order_by("created_at")]
