"""Сквозная проверка этапа 5 (задача 8 плана этапа 5 A).

Одна история на настоящих сервисах: счёт без договора -> альтернативы двух
снабженцев -> сравнение -> выбор (как сделает B5.1) -> новый счёт -> оплата ->
KPI «Подтверждён» -> отчёт R-01 -> закрытие АП решением ФД без выбора (AC-017).

1. Счёт без договора на 2 800 000 отправлен ФД; снабженцы получают уведомление
   «Можно предложить альтернативу» (ТЗ §12.2), автор документа — нет. (Автор —
   СН, а не ПМ: ПМ по матрице ролей альтернатив не подаёт, D-S5-1, а счёт ПМ
   через план закупок требует заявки ПМ — на суть цепочки это не влияет.)
2. СН-1 подаёт АП на 2 450 000 с КП; СН-2 подаёт более дорогую АП с обоснованием.
3. Сравнение: экономия 350 000 (12,50 %) у первой, удорожание у второй.
4. Выбор АП-1 — имитация B5.1: ``lifecycle.mark_selected`` + исходный счёт
   «Заменён альтернативой» + черновик нового счёта (``create_from_plan``) +
   ``kpi.create_preliminary``. АП-2 — «Не выбрано», KPI — «Предварительный».
5. Новый счёт отправлен, ФД «К оплате», БУХ «Оплачено» -> KPI «Подтверждён»,
   сумма и экономия заморожены. R-01: у СН-1 подано 1, подтверждено 1,
   экономия 350 000; у СН-2 подано 1, доля 0 %.
6. Второй счёт: ФД «К оплате» без выбора — его АП «Не выбрано» (AC-017).

Всё идёт сервисами внутри ``use_company`` (фикстура ``company_context``).
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.utils import timezone

from apps.bpp.models import Invoice, InvoiceStatus, KpiRecord, KpiStatus, OfferStatus
from apps.bpp.services.alternatives import kpi, lifecycle, read, report
from apps.bpp.services.invoices import decisions, payments
from apps.bpp.services.invoices import invoices as invoice_service
from apps.bpp.tests import stage2 as s
from apps.bpp.tests import test_invoices as invoice_flow
from apps.bpp.tests.alternatives import common
from apps.bpp.tests.test_files import memory_storage  # noqa: F401  (фикстура: хранилище в памяти)
from apps.companies.models import Company, CompanyMembership
from apps.notifications import interface as notifications
from htqweb.errors import DomainError

pytestmark = pytest.mark.django_db

D = Decimal
SOURCE_AMOUNT, OFFER_1, OFFER_2 = 2_800_000, 2_450_000, 3_000_000
AUTHOR, BUYER_1, BUYER_2, BUYER_3 = s.SN, common.SN2, common.SN3, common.SN4


def _people(slug):
    """Роли и членство: ``holders_of`` видит только участников компании."""
    company = Company.objects.get(slug=slug)
    for user_id, role in ((AUTHOR, "bpp-sn"), (BUYER_1, "bpp-sn"), (BUYER_2, "bpp-sn"),
                          (BUYER_3, "bpp-sn"), (s.FD, "bpp-fd")):
        s.user(user_id)
        s.grant(slug, user_id, role)
        CompanyMembership.objects.get_or_create(company=company, user_id=user_id)


def _titles(slug, user_id, event) -> list[str]:
    return [row["title"] for row in notifications.latest(user_id, company_slug=slug)
            if row["event"] == event]


def _rows(data) -> dict:
    return {row["buyer_id"]: row for row in data["rows"]}


def test_alternative_selected_paid_and_reported(company_context, memory_storage):  # noqa: F811
    slug = company_context["slug"]
    _people(slug)
    fd = invoice_flow._fd(slug)

    # 1. Счёт без договора: снабженцы уведомлены, автор — нет.
    proj = invoice_flow._setup(slug)
    author = common.sn(slug, AUTHOR)
    req = invoice_flow._approved_request(author, proj, SOURCE_AMOUNT)
    item_ids = [str(i.id) for i in req.items.all()]
    source = invoice_service.create_from_plan(author, item_ids)
    source, _ = invoice_service.update_draft(author, source.id, expected_version=None, data={
        "counterparty_id": str(invoice_flow._counterparty().pk), "ext_number": "145",
        "ext_date": timezone.localdate()})
    common.with_file(source, "invoice")
    source = invoice_service.submit(author, source.id, expected_version=None)
    assert source.status == InvoiceStatus.UNDER_REVIEW
    for buyer in (BUYER_1, BUYER_2, BUYER_3):
        (title,) = _titles(slug, buyer, lifecycle.EVENT_WINDOW)
        assert source.number in title and title.endswith("Можно предложить альтернативу")
    assert _titles(slug, AUTHOR, lifecycle.EVENT_WINDOW) == []

    # 2. СН-1 — дешевле, СН-2 — дороже, с обоснованием.
    offer_1 = common.filed(common.sn(slug, BUYER_1), source, common.cp(2), price=OFFER_1)
    offer_2 = common.filed(common.sn(slug, BUYER_2), source, common.cp(3), price=OFFER_2)
    assert offer_1.status == offer_2.status == OfferStatus.SUBMITTED
    assert (offer_1.saving_amount, offer_1.saving_pct) == (D("350000.00"), D("12.50"))
    assert offer_2.saving_amount == D("-200000.00") and offer_2.saving_pct < 0

    # 3. Сравнение: обе колонки, экономия и удорожание; варианты голоса.
    data = read.comparison(fd, "invoice", source.pk)
    columns = {col["id"]: col for col in data["offers"]}
    assert set(columns) == {str(offer_1.pk), str(offer_2.pk)}
    assert columns[str(offer_1.pk)]["saving"] == {
        "amount": "350000.00", "pct": "12.50", "more_expensive": False}
    assert columns[str(offer_2.pk)]["saving"]["more_expensive"] is True
    assert data["submitted_count"] == 2 and data["window_open"] is True
    assert {opt["key"] for opt in lifecycle.options_for("invoice", source.pk)} == {
        "original", f"offer:{offer_1.pk}", f"offer:{offer_2.pk}"}

    # 4. Выбор АП-1 — как сделает B5.1, в одной транзакции.
    chosen = lifecycle.mark_selected(offer_1.pk, actor_id=s.FD, comment="Дешевле на 12,5 %")
    Invoice.objects.filter(pk=source.pk).update(status=InvoiceStatus.REPLACED)
    new = invoice_service.create_from_plan(author, item_ids)
    chosen.result_type, chosen.result_id = "invoice", new.pk
    chosen.save(update_fields=["result_type", "result_id", "updated_at"])
    record = kpi.create_preliminary(chosen.pk, result_type="invoice", result_id=new.pk,
                                    selected_by_id=s.FD)
    offer_1.refresh_from_db(), offer_2.refresh_from_db()
    assert (offer_1.status, offer_2.status) == (OfferStatus.SELECTED, OfferStatus.NOT_SELECTED)
    assert record.status == KpiStatus.PRELIMINARY
    assert (record.buyer_id, record.source_amount_kzt) == (BUYER_1, D("2800000.00"))
    with pytest.raises(DomainError) as exc:  # BR-096: документ уже заменён
        lifecycle.mark_selected(offer_2.pk, actor_id=s.FD, comment="ещё раз")
    assert exc.value.code == "E-STATE-01"

    # 5. Новый счёт на сумму АП: отправка -> «К оплате» -> «Оплачено» -> «Подтверждён».
    (line,) = list(new.lines.all())
    new, _ = invoice_service.update_draft(author, new.id, expected_version=None, data={
        "counterparty_id": str(offer_1.counterparty_id), "ext_number": "145",
        "ext_date": timezone.localdate(), "amount": OFFER_1,
        "lines": [{"request_item_id": str(line.request_item_id), "qty": line.qty,
                   "amount": OFFER_1}]})
    common.with_file(new, "invoice")
    new = invoice_service.submit(author, new.id, expected_version=None)
    new = decisions.decide(fd, new.id, decision="pay")
    assert new.status == InvoiceStatus.TO_PAY
    record.refresh_from_db()
    assert (record.status, record.result_amount_kzt, record.saving_amount) == (
        KpiStatus.PRELIMINARY, D("2450000.00"), D("350000.00"))
    new = payments.mark_paid(invoice_flow._buh(slug), new.id, pay_date=timezone.localdate(),
                             amount=OFFER_1)
    assert new.status == InvoiceStatus.PAID
    record.refresh_from_db()
    assert (record.status, record.saving_amount, record.saving_pct) == (
        KpiStatus.CONFIRMED, D("350000.00"), D("12.50"))
    kpi.sync_for_document("invoice", new.pk)  # идемпотентна: подтверждённый заморожен
    assert KpiRecord.objects.get(offer=offer_1).status == KpiStatus.CONFIRMED

    data = report.report(fd, report.Filters())
    rows = _rows(data)
    a, b = rows[BUYER_1], rows[BUYER_2]
    assert (a["submitted"], a["selected"], a["confirmed"], a["saving"], a["share_pct"]) == (
        1, 1, 1, "350000.00", "100.00")
    assert (b["submitted"], b["selected"], b["confirmed"], b["saving"], b["share_pct"]) == (
        1, 0, 0, "0.00", "0.00")
    assert data["total"]["saving"] == "350000.00"

    # 6. Второй счёт: «К оплате» без выбора — АП «Не выбрано» (AC-017).
    _, _, second = invoice_flow._submitted(slug, 500_000, proj=proj, counterparty=common.cp(5))
    other = common.filed(common.sn(slug, BUYER_3), second, common.cp(6), price=400_000)
    assert other.status == OfferStatus.SUBMITTED
    decisions.decide(fd, second.id, decision="pay")
    other.refresh_from_db()
    assert other.status == OfferStatus.NOT_SELECTED and other.closed_reason
    assert not KpiRecord.objects.filter(offer=other).exists()
    assert _titles(slug, BUYER_3, lifecycle.EVENT_CLOSED)
