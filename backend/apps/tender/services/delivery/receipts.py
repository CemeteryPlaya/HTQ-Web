"""Приёмка (T5.5; спека этапа 5, §3 T5.5; ТЗ TND-041).

«Отметить получение» — автор тендера с узлом ``tender.receipts`` create:
дата (не позже сегодня), количество по строкам выбора (частичная приёмка
допустима; всего — не больше выбранного, иначе 422 ``E-TND-13``), СМР —
«Работы приняты» строкой выбора СМР. Сканы накладной, акта и счёт-фактуры
и фото — файлы владельца ``tender.receipt`` на панели файлов после создания.
«Оригиналы переданы в бухгалтерию» (дата, кому) — правкой приёмки.

После каждого изменения на счета поставщика в БЗО уходит отметка приёмки
(``bpp.set_acceptance``: последняя действующая дата; у счёта «после приёмки»
— срок оплаты), а тендер «Документы в БЗО» становится «Поставка». Ошибочная
приёмка отменяется датой с комментарием: количество к получению и дата на
счёте пересчитываются по оставшимся.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from apps.bpp import interface as bpp
from apps.tender.models import Receipt, ReceiptKind, ReceiptLine, TenderStatus
from apps.tender.services.core import audit
from apps.tender.services.tenders import tenders
from apps.tender.services.tenders.ctx import Ctx, bad
from htqweb.errors import DomainError

from . import closing, stages

NODE = "tender.receipts"
OPEN = (TenderStatus.HANDED_OVER, TenderStatus.DELIVERY)
COMMENT_MIN = 10


def _own(ctx: Ctx, tender_id, action: str):
    ctx.require(NODE, "create", "Недостаточно прав, чтобы отмечать приёмку.")
    tender = tenders.get_own(ctx, tender_id, action)
    if tender.status not in OPEN:
        raise tenders.state_error("отмечать приёмку в", tender)
    return tender


def _date(value, field: str) -> date:
    if isinstance(value, date):
        out = value
    else:
        try:
            out = date.fromisoformat(str(value))
        except (TypeError, ValueError):
            raise bad(field, "дата — ГГГГ-ММ-ДД") from None
    if out > timezone.localdate():
        raise bad(field, "дата приёмки — не позже сегодняшней")
    return out


def out(receipt: Receipt) -> dict:
    return {"id": str(receipt.pk), "invitation_id": str(receipt.invitation_id),
            "received_at": receipt.received_at.isoformat(), "kind": receipt.kind,
            "comment": receipt.comment,
            "originals_at": receipt.originals_at.isoformat() if receipt.originals_at else None,
            "originals_to": receipt.originals_to, "version": receipt.version,
            "cancelled_at": receipt.cancelled_at.isoformat() if receipt.cancelled_at else None,
            "lines": [{"award_id": str(line.award_id), "qty": str(line.qty)}
                      for line in receipt.lines.all()]}


def sync_acceptance(tender, invitation_id, actor_id: int) -> None:
    """Последняя действующая приёмка поставщика — на его счета в БЗО."""
    live = (Receipt.objects.filter(tender=tender, invitation_id=invitation_id,
                                   cancelled_at__isnull=True).order_by("-received_at"))
    latest = live.first()
    originals = live.exclude(originals_at=None).order_by("-originals_at").first()
    invoices = [d.doc_id for d in stages.supplier_documents(tender).get(str(invitation_id), [])
                if d.doc_type == "invoice" and d.status not in stages.DEAD]
    if invoices:
        bpp.set_acceptance(invoices, received_at=latest.received_at if latest else None,
                           originals_at=originals.originals_at if originals else None,
                           originals_to=originals.originals_to if originals else "",
                           actor=bpp.TenderActor(user_id=actor_id))


def _moved(tender, actor_id: int) -> None:
    if tender.status == TenderStatus.HANDED_OVER:
        tender.status = TenderStatus.DELIVERY
        tenders._touch(tender, actor_id)


@transaction.atomic
def create(ctx: Ctx, tender_id, data: dict) -> dict:
    tender = _own(ctx, tender_id, "Отмечать приёмку в")
    awards = {str(a.pk): a for a in tender.awards.select_related("extra", "offer")}
    invitation_id = str(data.get("invitation_id") or "")
    kind = data.get("kind") or ReceiptKind.GOODS
    if kind not in ReceiptKind.values:
        raise bad("kind", "вид приёмки — товар или работы")
    received = stages.received_by_award(tender)
    rows = []
    for i, row in enumerate(data.get("lines") or []):
        award = awards.get(str(row.get("award_id")))
        if award is None or str(award.offer.invitation_id) != invitation_id:
            raise bad(f"lines[{i}].award_id", "строка выбора не этого поставщика")
        is_works = bool(award.extra_id and award.extra.kind == "works")
        if award.extra_id and not is_works:
            raise bad(f"lines[{i}].award_id", "доставка принимается вместе с товаром")
        if is_works != (kind == ReceiptKind.WORKS):
            raise bad(f"lines[{i}].award_id", "СМР — «Работы приняты», товар — «Товар получен»")
        try:
            qty = Decimal(str(row.get("qty")))
        except (InvalidOperation, ValueError):
            raise bad(f"lines[{i}].qty", "количество — число") from None
        if qty <= 0:
            raise bad(f"lines[{i}].qty", "количество — больше нуля")
        left = award.qty - received[award.pk]
        if qty > left:
            raise DomainError("E-TND-13", f"Принять можно не больше {left} — остальное уже "
                                          f"принято.", fields=[{"field": f"lines[{i}].qty",
                                                                "message": f"Не больше {left}"}])
        received[award.pk] += qty
        rows.append((award, qty))
    if not rows:
        raise bad("lines", "отметьте, что принято")
    receipt = Receipt.objects.create(
        tender=tender, invitation_id=invitation_id, kind=kind,
        received_at=_date(data.get("received_at"), "received_at"),
        comment=(data.get("comment") or "").strip()[:2000],
        originals_at=(_date(data["originals_at"], "originals_at")
                      if data.get("originals_at") else None),
        originals_to=(data.get("originals_to") or "").strip()[:255],
        created_by=ctx.user_id, updated_by=ctx.user_id)
    ReceiptLine.objects.bulk_create([ReceiptLine(receipt=receipt, award=a, qty=q,
                                                 created_by=ctx.user_id, updated_by=ctx.user_id)
                                     for a, q in rows])
    _moved(tender, ctx.user_id)
    sync_acceptance(tender, invitation_id, ctx.user_id)
    closing.attach_for_supplier(tender, invitation_id)
    audit.record(tender, "receipt_added", actor_id=ctx.user_id,
                 changes={"receipt": str(receipt.pk), "invitation": invitation_id,
                          "received_at": receipt.received_at.isoformat(),
                          "lines": [{"award": str(a.pk), "qty": str(q)} for a, q in rows]})
    return out(receipt)


def _receipt(tender, receipt_id) -> Receipt:
    key = tenders._key(receipt_id)
    receipt = (Receipt.objects.select_for_update().filter(pk=key, tender=tender).first()
               if key else None)
    if receipt is None:
        raise DomainError("E-NOT-FOUND", "Приёмка не найдена.", status=404)
    if receipt.cancelled_at is not None:
        raise DomainError("E-STS-01", "Приёмка отменена.", status=409)
    return receipt


@transaction.atomic
def set_originals(ctx: Ctx, tender_id, receipt_id, data: dict) -> dict:
    tender = _own(ctx, tender_id, "Править приёмку в")
    receipt = _receipt(tender, receipt_id)
    receipt.originals_at = (_date(data["originals_at"], "originals_at")
                            if data.get("originals_at") else None)
    receipt.originals_to = (data.get("originals_to") or "").strip()[:255]
    tenders._touch(receipt, ctx.user_id)
    sync_acceptance(tender, receipt.invitation_id, ctx.user_id)
    audit.record(tender, "receipt_originals", actor_id=ctx.user_id,
                 changes={"receipt": str(receipt.pk), "originals_to": receipt.originals_to})
    return out(receipt)


@transaction.atomic
def cancel(ctx: Ctx, tender_id, receipt_id, *, comment: str) -> dict:
    tender = _own(ctx, tender_id, "Отменять приёмку в")
    receipt = _receipt(tender, receipt_id)
    comment = (comment or "").strip()
    if len(comment) < COMMENT_MIN:
        raise bad("comment", "причина отмены — не короче 10 символов")
    receipt.cancelled_at, receipt.cancelled_by = timezone.now(), ctx.user_id
    receipt.cancel_comment = comment[:2000]
    tenders._touch(receipt, ctx.user_id)
    sync_acceptance(tender, receipt.invitation_id, ctx.user_id)
    audit.record(tender, "receipt_cancelled", actor_id=ctx.user_id, comment=comment,
                 changes={"receipt": str(receipt.pk)})
    return out(receipt)


def list_for(ctx: Ctx, tender_id) -> list[dict]:
    tender = tenders.get_visible(ctx, tender_id)
    return [out(r) for r in tender.receipts.prefetch_related("lines").order_by("received_at",
                                                                             "created_at")]
