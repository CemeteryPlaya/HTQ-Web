"""Помощники тестов KPI снабжения (A5.2): выбор альтернативы — настоящий
``lifecycle.mark_selected`` (задача 3), ссылку на новый документ пишет, как
сделает B5.1, прямая запись, а запись KPI заводит настоящий
``kpi.create_preliminary``.
"""

from __future__ import annotations

import itertools
import uuid
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from apps.bpp.models import (
    Agreement,
    AgreementStatus,
    AlternativeOffer,
    KpiRecord,
    KpiStatus,
    OfferStatus,
)
from apps.bpp.services.alternatives import kpi, lifecycle
from apps.bpp.tests import stage2 as s
from apps.bpp.tests.bank.common import counterparty, orm_invoice

D = Decimal
SN_A, SN_B = 904, 906  # выданы в stage2: SN и SN2
_SEQ = itertools.count(1)
_AGR = itertools.count(1)

__all__ = ["D", "SN_A", "SN_B", "agreement", "cp", "invoice", "kpi_row", "select_offer",
           "submitted_offer"]


_CP = itertools.count(1)


def cp(n: int | None = None):
    """Новый контрагент с уникальным БИН: пара (страна, БИН) уникальна, а
    тесты берут «контрагента» по нескольку раз — параметр ``n`` не влияет."""
    return counterparty(f"3{next(_CP):011d}")


def invoice(amount, *, status="draft", counterparty_=None, project_id=None, article_id=None,
            author_id=SN_A, amount_kzt="same"):
    """Счёт прямо в базе; ``amount_kzt`` — как у KZT-счёта по умолчанию."""
    inv = orm_invoice(counterparty_ or cp(), amount, status=status, author_id=author_id)
    if project_id:
        inv.project_id = project_id
    if article_id:
        inv.article_id = article_id
    inv.amount_kzt = D(str(amount)) if amount_kzt == "same" else amount_kzt
    inv.save()
    return inv


def agreement(amount, *, status=AgreementStatus.ON_REVIEW, currency="KZT", author_id=SN_A,
              parent=None, counterparty_=None) -> Agreement:
    n = next(_AGR)
    return Agreement.objects.create(
        number=f"ДГ-2026-{700000 + n:06d}", project_id=uuid.uuid4(), article_id=uuid.uuid4(),
        counterparty=counterparty_ or cp(50 + n), ext_number=f"Д-{n}",
        ext_date=timezone.localdate(), amount=D(str(amount)), currency_code=currency,
        status=status, author_id=author_id, parent_agreement=parent)


def _offer_number() -> str:
    return f"АП-2026-{900000 + next(_SEQ):06d}"


def submitted_offer(source, *, author_id=SN_A, role="sn", status=OfferStatus.SUBMITTED,
                    days_ago=0, own=False, source_type="invoice") -> AlternativeOffer:
    return AlternativeOffer.objects.create(
        number=_offer_number(), source_type=source_type, source_id=source.pk,
        project_id=source.project_id, article_id=source.article_id, author_id=author_id,
        author_role=role, own_document=own, counterparty=cp(200 + next(_SEQ)),
        amount=D("100.00"), amount_kzt=D("100.00"), source_amount_kzt=D("200.00"),
        status=status, submitted_at=timezone.now() - timedelta(days=days_ago))


def select_offer(source, result, *, source_amount, author_id=SN_A, role="sn", own=False,
                 source_type="invoice", result_type="invoice", selected_by=900):
    """АП «Выбрано» + запись KPI «Предварительный» — как сделает B5.1:
    ``lifecycle.mark_selected`` (исходный документ — в окне подачи), ссылка на
    новый документ, ``kpi.create_preliminary``. ``source_amount`` — исходная
    часть в KZT."""
    offer = submitted_offer(source, author_id=author_id, role=role, own=own,
                            source_type=source_type)
    offer.source_amount_kzt = D(str(source_amount))
    offer.save()
    offer = lifecycle.mark_selected(offer.pk, actor_id=selected_by,
                                    comment="Дешевле при том же сроке поставки")
    offer.result_type, offer.result_id = result_type, result.pk
    offer.save(update_fields=["result_type", "result_id", "updated_at"])
    record = kpi.create_preliminary(offer.pk, result_type=result_type, result_id=result.pk,
                                    selected_by_id=selected_by)
    return offer, record


def kpi_row(*, buyer_id=SN_A, role="sn", status=KpiStatus.CONFIRMED, saving="0.00",
            own=False, days_ago=0, project_id=None, article_id=None) -> KpiRecord:
    """Запись KPI прямо в базе — для отчёта: экономия задана числом."""
    src = invoice(1000)
    offer = submitted_offer(src, author_id=buyer_id, role=role, status=OfferStatus.SELECTED,
                            own=own)
    saving = D(saving)
    return KpiRecord.objects.create(
        offer=offer, buyer_id=buyer_id, buyer_role=role, own_document=own,
        project_id=project_id or src.project_id, article_id=article_id or src.article_id,
        source_type="invoice", source_id=src.pk, source_number=src.number,
        source_amount_kzt=D("1000.00"), result_type="invoice", result_id=uuid.uuid4(),
        result_number="СЧ-X", result_amount_kzt=D("1000.00") - saving, saving_amount=saving,
        saving_pct=D("0.00"), selected_at=timezone.now() - timedelta(days=days_ago),
        selected_by_id=900, status=status)


def users():
    for uid in (s.FD, s.OD, s.TD, SN_A, SN_B, 907):
        s.user(uid)
