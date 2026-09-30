"""KPI снабжения: запись, подтверждение и аннулирование по статусу нового
документа, ручное аннулирование (план этапа 5 A, задача 5 — A5.2).

Выбор альтернативы — ``kpi_helpers.select_offer`` (настоящий
``lifecycle.mark_selected``, ссылка на новый документ — прямой записью вместо
B5.1, настоящий ``create_preliminary``);
смену статуса нового документа — либо настоящие сервисы счёта и договора
(хуки зоны B), либо прямая запись статуса и ``kpi.sync_for_document``.
"""

from __future__ import annotations

import pytest
from django.utils import timezone

from apps.bpp.models import AgreementStatus, AuditLog, InvoiceStatus, KpiRecord, KpiStatus
from apps.bpp.services.alternatives import kpi, report
from apps.bpp.services.invoices import invoices as invoice_service
from apps.bpp.services.invoices import payments
from apps.bpp.tests import stage2 as s
from apps.bpp.tests.alternatives.kpi_helpers import D, agreement, cp, invoice, select_offer, users
from htqweb.errors import DomainError

pytestmark = pytest.mark.django_db
BUH = 907


def _fd(slug):
    return s.actor(slug, s.FD, "bpp-fd")


def _world(amount_source=2_800_000, amount_new=2_450_000):
    users()
    src = invoice(amount_source, status=InvoiceStatus.UNDER_REVIEW)
    new = invoice(amount_new, status=InvoiceStatus.DRAFT, counterparty_=cp(2))
    offer, record = select_offer(src, new, source_amount=amount_source)
    return src, new, offer, record


def _set(doc, status):
    type(doc).objects.filter(pk=doc.pk).update(status=status)


def _fresh(record) -> KpiRecord:
    return KpiRecord.objects.get(pk=record.pk)


def _code(call) -> str:
    with pytest.raises(DomainError) as exc:
        call()
    return exc.value.code


# ── подтверждение ───────────────────────────────────────────────────────

def test_create_preliminary_snapshot(company_context):
    src, new, offer, record = _world()
    assert record.status == KpiStatus.PRELIMINARY
    assert record.buyer_id == offer.author_id and record.buyer_role == "sn"
    assert (record.source_number, record.result_number) == (src.number, new.number)
    assert record.source_amount_kzt == D("2800000.00")
    assert record.result_amount_kzt == D("2450000.00")
    assert record.saving_amount == D("350000.00") and record.saving_pct == D("12.50")
    assert AuditLog.objects.filter(object_type="bpp.kpirecord", object_id=str(record.pk),
                                   action="created").exists()
    # BR-096: вторая запись по той же АП невозможна.
    assert _code(lambda: kpi.create_preliminary(
        offer.pk, result_type="invoice", result_id=new.pk, selected_by_id=900)) == "E-STATE-01"


def test_ac015_preliminary_then_confirmed_on_paid(company_context):
    slug = company_context["slug"]
    _, new, _, record = _world()
    _set(new, InvoiceStatus.TO_PAY)
    payments.mark_paid(s.actor(slug, BUH, "bpp-buh"), new.pk, pay_date=timezone.localdate(),
                       amount=D("2450000.00"))
    got = _fresh(record)
    assert got.status == KpiStatus.CONFIRMED and got.status_changed_at is not None
    assert got.saving_amount == D("350000.00")


def test_partially_paid_keeps_preliminary(company_context):
    slug = company_context["slug"]
    _, new, _, record = _world()
    _set(new, InvoiceStatus.TO_PAY)
    payments.mark_paid(s.actor(slug, BUH, "bpp-buh"), new.pk, pay_date=timezone.localdate(),
                       amount=D("1000000.00"))
    assert _fresh(record).status == KpiStatus.PRELIMINARY


def test_ac019_not_payable_annuls_and_excludes_from_kpi(company_context):
    slug = company_context["slug"]
    _, new, _, record = _world()
    _set(new, InvoiceStatus.UNDER_REVIEW)
    invoice_service.on_rejected(new.pk)  # решение ФД «Не к оплате»
    got = _fresh(record)
    assert got.status == KpiStatus.ANNULLED and got.status_changed_at is not None
    data = report.report(_fd(slug), report.Filters())
    assert data["total"]["confirmed"] == 0 and data["total"]["saving"] == "0.00"


@pytest.mark.parametrize("status", [InvoiceStatus.CANCELLED, InvoiceStatus.REPLACED])
def test_cancelled_and_replaced_invoice_annul(company_context, status):
    _, new, _, record = _world()
    _set(new, status)
    kpi.sync_for_document("invoice", new.pk)
    assert _fresh(record).status == KpiStatus.ANNULLED


@pytest.mark.parametrize("status", [InvoiceStatus.AWAITING_DOCS, InvoiceStatus.DOCS_PROVIDED,
                                    InvoiceStatus.CLOSED])
def test_closing_axis_confirms(company_context, status):
    _, new, _, record = _world()
    _set(new, status)
    kpi.sync_for_document("invoice", new.pk)
    assert _fresh(record).status == KpiStatus.CONFIRMED


def test_preliminary_recomputes_saving_on_new_amount(company_context):
    _, new, _, record = _world()
    type(new).objects.filter(pk=new.pk).update(amount=D("2400000.00"),
                                                amount_kzt=D("2400000.00"))
    kpi.sync_for_document("invoice", new.pk)
    got = _fresh(record)
    assert got.result_amount_kzt == D("2400000.00") and got.saving_amount == D("400000.00")

    _set(new, InvoiceStatus.PAID)
    kpi.sync_for_document("invoice", new.pk)
    assert _fresh(record).status == KpiStatus.CONFIRMED
    # После «Подтверждён» сумма и экономия заморожены.
    type(new).objects.filter(pk=new.pk).update(amount_kzt=D("1000000.00"))
    kpi.sync_for_document("invoice", new.pk)
    got = _fresh(record)
    assert got.result_amount_kzt == D("2400000.00") and got.saving_amount == D("400000.00")


def test_sync_is_idempotent_and_unmark_does_not_revert(company_context):
    _, new, _, record = _world()
    _set(new, InvoiceStatus.PAID)
    kpi.sync_for_document("invoice", new.pk)
    once = _fresh(record)
    events = AuditLog.objects.filter(object_id=str(record.pk)).count()
    kpi.sync_for_document("invoice", new.pk)
    again = _fresh(record)
    assert (again.version, again.status) == (once.version, KpiStatus.CONFIRMED)
    assert AuditLog.objects.filter(object_id=str(record.pk)).count() == events
    # Снятая отметка БУХ (счёт снова «К оплате») подтверждённый KPI не откатывает.
    _set(new, InvoiceStatus.TO_PAY)
    kpi.sync_for_document("invoice", new.pk)
    assert _fresh(record).status == KpiStatus.CONFIRMED
    # Документ без записи KPI и чужой тип ключа функция не замечает.
    kpi.sync_for_document("invoice", invoice(10).pk)
    kpi.sync_for_document("agreement", new.pk)


def test_annulled_is_final(company_context):
    _, new, _, record = _world()
    _set(new, InvoiceStatus.CANCELLED)
    kpi.sync_for_document("invoice", new.pk)
    _set(new, InvoiceStatus.PAID)
    kpi.sync_for_document("invoice", new.pk)
    assert _fresh(record).status == KpiStatus.ANNULLED


# ── договор ─────────────────────────────────────────────────────────────

def _agreement_world(amount=2_450_000):
    users()
    src = invoice(2_800_000, status=InvoiceStatus.UNDER_REVIEW)
    agr = agreement(amount)
    offer, record = select_offer(src, agr, source_amount=2_800_000, result_type="agreement")
    return src, agr, offer, record


def test_agreement_active_confirms_and_rejected_annuls(company_context):
    _, agr, _, record = _agreement_world()
    assert record.result_amount_kzt == D("2450000.00")
    _set(agr, AgreementStatus.ACTIVE)
    kpi.sync_for_document("agreement", agr.pk)
    assert _fresh(record).status == KpiStatus.CONFIRMED

    _, agr2, _, record2 = _agreement_world()
    _set(agr2, AgreementStatus.REJECTED)
    kpi.sync_for_document("agreement", agr2.pk)
    assert _fresh(record2).status == KpiStatus.ANNULLED


def test_agreement_fulfilled_confirms(company_context):
    _, agr, _, record = _agreement_world()
    _set(agr, AgreementStatus.FULFILLED)
    kpi.sync_for_document("agreement", agr.pk)
    assert _fresh(record).status == KpiStatus.CONFIRMED


def test_supplement_does_not_change_confirmed_saving(company_context):
    _, agr, _, record = _agreement_world()
    _set(agr, AgreementStatus.ACTIVE)
    kpi.sync_for_document("agreement", agr.pk)
    before = _fresh(record)
    supplement = agreement(900_000, status=AgreementStatus.ACTIVE, parent=agr)
    kpi.sync_for_document("agreement", supplement.pk)  # у допсоглашения записи нет
    kpi.sync_for_document("agreement", agr.pk)
    after = _fresh(record)
    assert (after.saving_amount, after.result_amount_kzt, after.version) == (
        before.saving_amount, before.result_amount_kzt, before.version)
    assert after.saving_amount == D("350000.00")


def test_terminated_without_paid_invoices_annuls(company_context):
    _, agr, _, record = _agreement_world()
    _set(agr, AgreementStatus.ACTIVE)
    kpi.sync_for_document("agreement", agr.pk)
    _set(agr, AgreementStatus.TERMINATED)
    kpi.sync_for_document("agreement", agr.pk)
    assert _fresh(record).status == KpiStatus.ANNULLED


def test_terminated_with_paid_invoice_stays_confirmed(company_context):
    _, agr, _, record = _agreement_world()
    _set(agr, AgreementStatus.ACTIVE)
    kpi.sync_for_document("agreement", agr.pk)
    paid = invoice(100, status=InvoiceStatus.PAID, counterparty_=cp(3))
    paid.agreement, paid.basis = agr, "contract"  # ck_bpp_invoice_basis
    paid.save()
    _set(agr, AgreementStatus.TERMINATED)
    kpi.sync_for_document("agreement", agr.pk)
    assert _fresh(record).status == KpiStatus.CONFIRMED


# ── ручное аннулирование ────────────────────────────────────────────────

def test_manual_annul_requires_fd_and_10_chars(company_context):
    slug = company_context["slug"]
    _, _, _, record = _world()
    sn = s.actor(slug, 904, "bpp-sn")
    assert _code(lambda: kpi.annul(sn, record.pk, comment="Достаточно длинный",
                                   expected_version=None)) == "E-ACC-01"
    fd = _fd(slug)
    assert _code(lambda: kpi.annul(fd, record.pk, comment="коротко",
                                   expected_version=None)) == "BR-060"
    assert _code(lambda: kpi.annul(fd, record.pk, comment="Достаточно длинный",
                                   expected_version=record.version + 5)) == "E-CON-01"
    done = kpi.annul(fd, record.pk, comment="  Ошибочный выбор поставщика ",
                     expected_version=record.version)
    assert done.status == KpiStatus.ANNULLED and done.annulled_by_id == s.FD
    assert done.annul_comment == "Ошибочный выбор поставщика"
    assert AuditLog.objects.filter(object_id=str(record.pk), action="annulled",
                                   actor_id=s.FD).exists()
    assert _code(lambda: kpi.annul(fd, record.pk, comment="Ещё раз аннулирую",
                                   expected_version=None)) == "E-STATE-01"


def test_manual_annul_of_confirmed(company_context):
    slug = company_context["slug"]
    _, new, _, record = _world()
    _set(new, InvoiceStatus.PAID)
    kpi.sync_for_document("invoice", new.pk)
    done = kpi.annul(_fd(slug), record.pk, comment="Счёт оплачен ошибочно", expected_version=None)
    assert done.status == KpiStatus.ANNULLED


def test_own_document_flag_in_record_ac018(company_context):
    users()
    src = invoice(1000, status=InvoiceStatus.UNDER_REVIEW)
    new = invoice(900, counterparty_=cp(4))
    _, record = select_offer(src, new, source_amount=1000, own=True)
    assert record.own_document is True
    assert record.saving_amount == D("100.00")
