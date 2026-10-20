"""«Закрыть остаток» (S5-13; спека этапа 5, §3 T5.5 п.5).

Передача в БЗО закрывает части заявки без единого выбора, а у частично
выбранной части невыбранные позиции и недобранное количество остаются в её ЗЗ
открытыми — под ними держится резерв бюджета. Закупщик (автор тендера)
закрывает этот остаток сам, когда документы части согласованы: остаток ЗЗ
аннулируется в БЗО (``bpp.cancel_requests_from_tender`` → «Закрыть остаток»),
резерв падает до выставленных документов. «Новый тендер на остаток» — этап 6.

- Кандидат — часть с переданными документами, ЗЗ «Утверждена», где выбрано
  меньше запрошенного хотя бы по одной позиции.
- Документ части ещё не согласован (черновик, на рассмотрении или
  согласовании, на доработке) — 409 ``E-STS-01``: «Закрыть остаток» в БЗО
  аннулирует открытые позиции, и несогласованный документ остался бы без них.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from django.db import transaction

from apps.bpp import interface as bpp
from apps.tender.models import Tender, TenderRequestPart, TenderStatus
from apps.tender.services.core import audit
from apps.tender.services.core.errors import check_version
from apps.tender.services.delivery import stages
from apps.tender.services.tenders import tenders
from apps.tender.services.tenders.ctx import Ctx, bad
from htqweb.errors import DomainError

COMMENT_MIN = 10
OPEN = (TenderStatus.HANDED_OVER, TenderStatus.DELIVERY)
ZERO = Decimal("0")


def candidates(tender: Tender) -> list[TenderRequestPart]:
    """Части, у которых есть что закрыть (см. модуль)."""
    if tender.status not in OPEN:
        return []
    handed = set(tender.handovers.values_list("part_id", flat=True))
    awarded: dict = defaultdict(lambda: ZERO)
    for item_id, qty in tender.awards.filter(line__isnull=False).values_list("line__item_id",
                                                                             "qty"):
        awarded[item_id] += qty
    out = []
    for part in (tender.request.parts.filter(pk__in=handed, excluded_at__isnull=True,
                                             bpp_status="approved")
                 .exclude(bpp_request_id=None).order_by("created_at")):
        if any(awarded[item.pk] < item.qty for item in part.items.all()):
            out.append(part)
    return out


def _unapproved(parts: list[TenderRequestPart]) -> list[str]:
    """Номера несогласованных документов частей."""
    rows = bpp.documents_status([str(p.bpp_request_id) for p in parts])
    return [row.number for row in rows
            if row.status not in stages.DEAD
            and not (row.doc_type == "invoice" and row.status in stages.LIVE_INVOICE)
            and not (row.doc_type == "agreement" and row.status in stages.LIVE_AGREEMENT)]


@transaction.atomic
def close_remainder(ctx: Ctx, tender_id, *, expected_version: int | None,
                    comment: str) -> Tender:
    tender = tenders.get_own(ctx, tender_id, "Закрывать остаток в")
    if tender.status not in OPEN:
        raise tenders.state_error("закрыть остаток в", tender)
    check_version(tender, expected_version)
    comment = (comment or "").strip()
    if len(comment) < COMMENT_MIN:
        raise bad("comment", "причина — не короче 10 символов")
    parts = candidates(tender)
    if not parts:
        raise DomainError("E-STS-01", "Остатка нет: по каждой позиции выбрано всё "
                                      "запрошенное или часть уже закрыта.", status=409)
    pending = _unapproved(parts)
    if pending:
        raise DomainError("E-STS-01", "Сначала согласуйте документы части: "
                                      f"{', '.join(pending)} — остаток закрывается после них.",
                          status=409, details={"documents": pending})
    bpp.cancel_requests_from_tender(
        [str(p.bpp_request_id) for p in parts], actor=bpp.TenderActor(user_id=tender.author_id),
        comment=f"Остаток после тендера {tender.number}: {comment}")
    tenders._touch(tender, ctx.user_id)
    audit.record(tender, "remainder_closed", actor_id=ctx.user_id, comment=comment,
                 changes={"parts": [str(p.pk) for p in parts],
                          "requests": [p.bpp_number for p in parts]})
    return tender
