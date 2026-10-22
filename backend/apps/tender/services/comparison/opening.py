"""Вскрытие предложений (T5.1; спека этапа 5, §3 T5.1, S5-02).

Вскрывает автор тендера: после срока приёма — всегда, до срока — только
когда каждое живое приглашение подало предложение или отказалось (иначе тому,
кто ещё заполняет, закрыли бы приём раньше обещанного). Вскрытие фиксирует
``opened_at`` и дату курса сравнения ``rate_date``; приглашения без
отправленной версии получают «Срок истёк». Ни одного отправленного
предложения — тендер «Не состоялся», заявка снова «Утверждена».

После вскрытия портал правку не принимает (статус ≠ «Приём», уже так в
``portal/offers._lock``), а предложения, файлы КП и сравнение открываются
тем, кто видит тендер (``require_opened``). ``ctx=None`` — вызов закрытия
приёма по сроку из beat этапа 4 (T4.3) от технической учётки портала.
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.tender.models import InvitationStatus, Tender, TenderStatus
from apps.tender.services.core import audit
from apps.tender.services.core.errors import check_version
from apps.tender.services.portal.actor import portal_actor
from apps.tender.services.tenders import tenders
from apps.tender.services.tenders.ctx import Ctx
from htqweb.errors import DomainError


def is_opened(tender: Tender) -> bool:
    return tender.opened_at is not None


def require_opened(tender: Tender) -> None:
    """Предложения, их файлы и сравнение — только после вскрытия, даже ФД
    (ТЗ TND-020): 409 ``E-TND-07``."""
    if not is_opened(tender):
        raise DomainError("E-TND-07", "Предложения откроются после вскрытия тендера.",
                          status=409)


@transaction.atomic
def open_tender(ctx: Ctx | None, tender_id, *, expected_version: int | None = None) -> Tender:
    if ctx is None:
        tender = Tender.objects.select_for_update().get(pk=tender_id)
        actor_id = portal_actor()
    else:
        tender = tenders.get_own(ctx, tender_id, "Вскрывать")
        actor_id = ctx.user_id
    if tender.status != TenderStatus.INTAKE:
        raise tenders.state_error("вскрыть", tender)
    check_version(tender, expected_version)
    if not tenders.may_open(tender):
        raise DomainError(
            "E-STS-01", f"До срока приёма вскрыть тендер {tender.number} можно, только когда "
                        f"все участники подали предложения или отказались.", status=409)
    now = timezone.now()
    live = tender.invitations.filter(revoked_at__isnull=True)
    expired = live.exclude(status__in=[InvitationStatus.SUBMITTED, InvitationStatus.DECLINED])
    expired_count = expired.update(status=InvitationStatus.EXPIRED, updated_by=actor_id,
                                   updated_at=now)
    submitted = live.filter(status=InvitationStatus.SUBMITTED).count()
    tender.opened_at = now
    tender.rate_date = timezone.localdate(now)
    if submitted == 0:
        tender.status = TenderStatus.FAILED
        tenders._touch(tender, actor_id)
        tenders.release_request(tender, actor_id)
        audit.record(tender, "failed", actor_id=actor_id,
                     changes={"invitations_expired": expired_count})
        return tender
    tender.status = TenderStatus.OPENED
    tenders._touch(tender, actor_id)
    audit.record(tender, "opened", actor_id=actor_id,
                 changes={"offers": submitted, "invitations_expired": expired_count,
                          "rate_date": tender.rate_date.isoformat()})
    return tender
