"""Проверки выбора альтернативы и нового документа по ней (B5.1).

- **BR-093** — альтернатива дороже исходной части на Δ: Δ не больше
  свободного остатка статьи на момент выбора.
- **Допуск 5 %** (ТЗ §12.4 п.5) — сумма нового документа при отправке
  отличается от АП не больше чем на 5 %; больше — нужен повторный выбор.

Модуль не импортирует сервисы счёта и договора: его зовут из их ``submit``
(иначе цикл импорта). Связь «АП → новый документ» — ``AlternativeOffer.
result_type``/``result_id`` (D-B51-3), отдельных столбцов у документов нет.
"""

from __future__ import annotations

from decimal import Decimal

from django.utils import timezone

from apps.bpp.models import Agreement, AlternativeOffer, Invoice, OfferStatus
from apps.bpp.services import calc
from apps.bpp.services.budget import balance as budget_balance
from apps.bpp.services.money import fmt, money
from htqweb.errors import DomainError

#: Допуск суммы нового документа к сумме АП без повторного выбора (§12.4 п.5).
TOLERANCE = Decimal("0.05")


def basis_offer(doc_type: str, doc_id) -> AlternativeOffer | None:
    """Выбранная АП, по которой создан документ, или ``None``."""
    return (AlternativeOffer.objects.select_related("counterparty")
            .filter(result_type=doc_type, result_id=doc_id, status=OfferStatus.SELECTED)
            .first())


def price_delta(offer: AlternativeOffer) -> Decimal:
    """На сколько АП дороже исходной части в KZT (CALC-013 наоборот)."""
    return money((offer.amount_kzt or Decimal("0")) - (offer.source_amount_kzt or Decimal("0")))


def budget_reason(offer: AlternativeOffer, *, project_id, article_id) -> str | None:
    """BR-093: ``None`` — остатка хватает; иначе текст отказа (ТЗ дословно)."""
    delta = price_delta(offer)
    if delta <= 0:
        return None
    available = money(budget_balance.balance(str(project_id), str(article_id))["available"])
    if delta <= available:
        return None
    return (f"Альтернатива дороже исходного предложения на {fmt(delta)}, свободного "
            f"остатка статьи {fmt(available)} недостаточно.")


def check_budget(offer: AlternativeOffer, *, project_id, article_id) -> None:
    reason = budget_reason(offer, project_id=project_id, article_id=article_id)
    if reason:
        raise DomainError("BR-093", reason,
                          fields=[{"field": "offer_id", "message": "Не хватает остатка статьи"}])


def document_kzt(doc) -> Decimal | None:
    """Сумма документа в KZT: у счёта — пересчитанная ``amount_kzt``, у
    договора — по курсу НБРК на дату документа (как KPI A5.2). Нет суммы или
    курса — ``None``."""
    if isinstance(doc, Invoice):
        return doc.amount_kzt
    if doc.amount is None:
        return None
    if doc.currency_code == calc.KZT:
        return money(doc.amount)
    try:
        return calc.to_kzt(doc.amount, doc.currency_code,
                           doc.ext_date or timezone.localdate()).amount_kzt
    except DomainError:
        return None


def check_within_tolerance(doc_type: str, doc, amount_kzt) -> None:
    """При отправке нового документа (основание — АП): сумма в KZT в пределах
    5 % от АП. Документ не по АП или сумма ещё не пересчитана — без проверки."""
    offer = basis_offer(doc_type, doc.pk)
    if offer is None or offer.amount_kzt is None or amount_kzt is None:
        return
    base = money(offer.amount_kzt)
    if base <= 0:
        return
    if abs(money(amount_kzt) - base) <= money(base * TOLERANCE):
        return
    raise DomainError(
        "E-VAL-01",
        f"Сумма {doc.number} — {fmt(amount_kzt)} — отличается от альтернативы "
        f"{offer.number} ({fmt(base)}) больше чем на 5 %. Приведите сумму к предложению "
        f"или запросите повторный выбор альтернативы.",
        fields=[{"field": "amount", "message": "Больше 5 % от альтернативы"}])


def alternative_links(doc_type: str, doc) -> dict:
    """Для карточки документа (D-B51-3): ``basis`` — АП, по которой документ
    создан («Основание: альтернатива АП-…»), ``replaced_by`` — чем заменён
    исходный документ (АП и новый документ). Нет связи — ``None``."""
    basis = basis_offer(doc_type, doc.pk)
    chosen = (AlternativeOffer.objects
              .filter(source_type=doc_type, source_id=doc.pk, status=OfferStatus.SELECTED)
              .first())
    replaced_by = None
    if chosen is not None:
        result = _document(chosen.result_type, chosen.result_id)
        replaced_by = {"offer_id": str(chosen.pk), "offer_number": chosen.number,
                       "result_type": chosen.result_type or None,
                       "result_id": str(chosen.result_id) if chosen.result_id else None,
                       "result_number": result.number if result is not None else None}
    return {"basis": None if basis is None else {"offer_id": str(basis.pk),
                                                  "offer_number": basis.number},
            "replaced_by": replaced_by}


def _document(doc_type: str, doc_id):
    model = {"invoice": Invoice, "agreement": Agreement}.get(doc_type or "")
    return model.objects.filter(pk=doc_id).first() if model and doc_id else None
