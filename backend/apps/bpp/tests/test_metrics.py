"""Бизнес-метрики модуля БЗО (задача A3.2, части 1 и 2; Review Focus 5).

Сама метрика — ``apps/bpp/metrics.py::collect`` в схеме одной компании;
веер по компаниям и метка ``company`` — ``apps.core.metrics.collect_all``.
Сторожа наблюдаемости (панель и правило на каждую метрику) —
``apps/core/tests/test_metrics_are_observed.py``.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta
from decimal import Decimal

import pytest
from django.core.cache import cache
from django.utils import timezone

from apps.bpp import metrics
from apps.bpp.interface import closing_docs_pending_for_user
from apps.bpp.models import Invoice, InvoiceStatus, PurchaseRequest, RequestStatus
from apps.bpp.models.bank import (
    BankImport,
    BankImportStatus,
    OrgBankAccount,
    StatementFormat,
    StatementTemplate,
)
from apps.bpp.models.settings import ModuleSetting
from apps.bpp.services.budget import check
from apps.bpp.services.budget import committed as calc
from apps.bpp.services.invoices import decisions, payments
from apps.bpp.services.requests import requests as service
from apps.bpp.tests import stage2 as s
# Счёт — модель B (B3.2); проводим его настоящими сервисами через фабрики
# его тестов, а не собираем руками только нужные метрике поля.
from apps.bpp.tests import test_invoices as invoice_flow
from apps.companies.models import Company, CompanyModule
from apps.signoff.models import ApprovalProcessStage
from htqweb.fallback import FallbackNotAllowed
from htqweb.tenancy.db import use_company

pytestmark = pytest.mark.django_db

LONG_AGO = timedelta(days=30)      # заведомо больше 5 рабочих дней


def _value(collected: dict, name: str):
    return collected[name]["values"][0][1]


def _setup(slug):
    proj, art = s.project(), s.metal()
    s.approved_budget(slug, proj, {art: 10_000_000})
    s.request_route()
    return proj, art, s.actor(slug, s.SN, "bpp-sn")


def _draft(sn, proj, art, amount=100):
    return service.create_draft(sn, {**s.header(proj, art),
                                     "items": s.items((1, amount))})


def _submitted(sn, proj, art):
    return service.submit(sn, _draft(sn, proj, art).id, expected_version=None)


# ── очередь заявок ──────────────────────────────────────────────────────

def test_requests_in_approval_and_stale_by_current_stage(company_context):
    slug = company_context["slug"]
    proj, art, sn = _setup(slug)
    old = timezone.now() - LONG_AGO

    # Отправлена давно, но текущий этап активирован только что: не застряла —
    # отсчёт идёт от этапа, а не от последней правки заявки.
    fresh_stage = _submitted(sn, proj, art)
    PurchaseRequest.objects.filter(pk=fresh_stage.pk).update(updated_at=old)
    # Текущий этап висит месяц — застряла.
    old_stage = _submitted(sn, proj, art)
    ApprovalProcessStage.objects.filter(
        process__subject_type=PurchaseRequest.SIGNOFF_SUBJECT_TYPE,
        process__subject_id=str(old_stage.pk)).update(activated_at=old)
    # «На согласовании» без идущего процесса — отсчёт от правки заявки.
    orphan = _draft(sn, proj, art)
    PurchaseRequest.objects.filter(pk=orphan.pk).update(
        status=RequestStatus.IN_APPROVAL, updated_at=old)
    # Не в счёт: черновик и техническая заявка переноса.
    _draft(sn, proj, art)
    migrated = _draft(sn, proj, art)
    PurchaseRequest.objects.filter(pk=migrated.pk).update(
        status=RequestStatus.IN_APPROVAL, is_migrated=True, updated_at=old)

    collected = metrics.collect()
    assert _value(collected, "bpp_requests_in_approval") == 3
    assert _value(collected, "bpp_requests_in_approval_stale") == 2


def test_empty_queue_is_zero_not_absent(company_context):
    collected = metrics.collect()
    assert _value(collected, "bpp_requests_in_approval") == 0
    assert _value(collected, "bpp_requests_in_approval_stale") == 0


def test_signoff_off_at_the_company_drops_only_the_stale_metric(company_context):
    slug = company_context["slug"]
    proj, art, sn = _setup(slug)
    req = _draft(sn, proj, art)
    PurchaseRequest.objects.filter(pk=req.pk).update(status=RequestStatus.IN_APPROVAL)
    CompanyModule.objects.create(company_id=company_context["id"], app_label="signoff",
                                 enabled=False)
    cache.clear()          # module_enabled кэширует рубильник на 5 с

    collected = metrics.collect()
    assert _value(collected, "bpp_requests_in_approval") == 1
    assert "bpp_requests_in_approval_stale" not in collected


@pytest.mark.parametrize(("today", "sent", "stale"), [
    # Пн 28.09.2026: пять рабочих дней назад — Пн 21.09.
    (date(2026, 9, 28), date(2026, 9, 21), False),
    (date(2026, 9, 28), date(2026, 9, 18), True),     # Пт — шесть рабочих
    # Ср 30.09: пять рабочих назад — Ср 23.09; выходные не считаются.
    (date(2026, 9, 30), date(2026, 9, 23), False),
    (date(2026, 9, 30), date(2026, 9, 22), True),
])
def test_stale_threshold_counts_working_days(today, sent, stale):
    now = timezone.make_aware(datetime.combine(today, time(12)))
    since = timezone.make_aware(datetime.combine(sent, time(9)))
    assert (since < metrics._stale_before(now)) is stale


# ── ночная сверка «Задействовано» (D-S3-4) ───────────────────────────────

def test_no_check_result_exports_neither_check_metric(company_context):
    collected = metrics.collect()
    assert "bpp_committed_mismatches" not in collected
    assert "bpp_committed_check_age_seconds" not in collected


def test_check_run_persists_its_result(company_context):
    assert check.run() == {"mismatches": 0}
    value = ModuleSetting.objects.get(pk=check.RESULT_KEY).value
    assert value["count"] == 0

    collected = metrics.collect()
    assert _value(collected, "bpp_committed_mismatches") == 0
    assert 0 <= _value(collected, "bpp_committed_check_age_seconds") < 60


def test_check_run_persists_a_mismatch_before_failing_loudly(company_context, monkeypatch):
    slug = company_context["slug"]
    proj, art, sn = _setup(slug)
    req = _draft(sn, proj, art)
    PurchaseRequest.objects.filter(pk=req.pk).update(status=RequestStatus.APPROVED)
    monkeypatch.setattr(calc, "_item_reference", lambda item: Decimal("1.00"))

    # Строгий режим роняет сверку на расхождении — но итог уже записан.
    with pytest.raises(FallbackNotAllowed):
        check.run()
    assert ModuleSetting.objects.get(pk=check.RESULT_KEY).value["count"] == 1
    assert _value(metrics.collect(), "bpp_committed_mismatches") == 1


def test_check_age_grows_from_the_recorded_time(company_context):
    at = timezone.now() - timedelta(hours=30)
    ModuleSetting.objects.create(key=check.RESULT_KEY,
                                 value={"count": 2, "at": at.isoformat()})
    collected = metrics.collect()
    assert _value(collected, "bpp_committed_mismatches") == 2
    assert 30 * 3600 <= _value(collected, "bpp_committed_check_age_seconds") < 30 * 3600 + 60


# ── загрузки выписок ────────────────────────────────────────────────────

def test_failed_bank_imports_of_the_last_week(company_context):
    template = StatementTemplate.objects.create(name="CSV банка", format=StatementFormat.CSV)
    account = OrgBankAccount.objects.create(iban="KZ000000000000000000", bic="HSBKKZKX",
                                            template=template)
    today = timezone.localdate()

    def made(number, status, age_days):
        row = BankImport.objects.create(number=number, account=account,
                                        format=StatementFormat.CSV, period_from=today,
                                        period_to=today, status=status)
        BankImport.objects.filter(pk=row.pk).update(
            created_at=timezone.now() - timedelta(days=age_days))

    made("ВП-2026-0001", BankImportStatus.FAILED, 1)
    made("ВП-2026-0002", BankImportStatus.FAILED, 6)
    made("ВП-2026-0003", BankImportStatus.FAILED, 10)       # старше недели
    made("ВП-2026-0004", BankImportStatus.LOADED, 1)

    assert _value(metrics.collect(), "bpp_bank_imports_failed") == 2


# ── очереди счетов и закрывающие документы (часть 2) ─────────────────────

_INVOICE_METRICS = ("bpp_invoices_awaiting_fd", "bpp_invoices_to_pay",
                    "bpp_invoices_closing_docs_overdue")


def _invoice_values() -> tuple:
    collected = metrics.collect()
    return tuple(_value(collected, name) for name in _INVOICE_METRICS)


def test_invoice_queues_follow_the_real_lifecycle(company_context):
    slug = company_context["slug"]
    _, _, inv = invoice_flow._submitted(slug, 1000)
    assert _invoice_values() == (1, 0, 0)          # на рассмотрении ФД

    decisions.decide(invoice_flow._fd(slug), inv.id, decision="pay")
    assert _invoice_values() == (0, 1, 0)          # к оплате — очередь БУХ

    buh, today = invoice_flow._buh(slug), timezone.localdate()
    payments.mark_paid(buh, inv.id, pay_date=today, amount=400)
    # «Оплачено частично» остаётся в очереди БУХ — как вкладка «К оплате».
    assert _invoice_values() == (0, 1, 0)
    payments.mark_paid(buh, inv.id, pay_date=today, amount=600)
    assert _invoice_values() == (0, 0, 0)

    payments.request_docs(buh, inv.id)
    assert _invoice_values() == (0, 0, 0)          # только что запрошены
    Invoice.objects.filter(pk=inv.pk).update(
        docs_requested_at=timezone.now() - timedelta(days=6))
    assert _invoice_values() == (0, 0, 1)
    # Метрика считает дни так же, как раздел сводки автора и карточка счёта.
    assert closing_docs_pending_for_user(s.SN)[0]["days"] == 6


def _raw_invoice(n, status, *, requested=None, migrated=False, updated=None):
    inv = Invoice.objects.create(number=f"СЧ-2026-{n:06d}", project_id=uuid.uuid4(),
                                 article_id=uuid.uuid4(), author_id=1, status=status,
                                 docs_requested_at=requested, is_migrated=migrated)
    if updated is not None:
        Invoice.objects.filter(pk=inv.pk).update(updated_at=updated)
    return inv


def test_invoices_off_at_the_company_drop_the_invoice_metrics(company_context):
    """Счета выключены у компании — очередей нет и действовать некому: метрики
    счетов не отдаются (иначе правило о закрывающих горело бы неделями), а
    остальные метрики модуля — на месте."""
    _raw_invoice(1, InvoiceStatus.AWAITING_DOCS,
                 requested=timezone.now() - timedelta(days=30))
    CompanyModule.objects.create(company_id=company_context["id"],
                                 app_label="bpp_invoices", enabled=False)
    cache.clear()          # module_enabled кэширует рубильник на 5 с

    collected = metrics.collect()
    assert not set(_INVOICE_METRICS) & set(collected)
    assert _value(collected, "bpp_requests_in_approval") == 0


def _local(days_ago: int, at: time) -> datetime:
    return timezone.make_aware(datetime.combine(
        timezone.localdate() - timedelta(days=days_ago), at))


def test_invoice_metrics_by_status_boundary_and_migration(company_context):
    st = InvoiceStatus
    _raw_invoice(1, st.UNDER_REVIEW)
    _raw_invoice(2, st.UNDER_REVIEW)
    _raw_invoice(3, st.TO_PAY)
    _raw_invoice(4, st.PARTIALLY_PAID)
    # Ровно пять дней — в любое время суток — ещё не просрочка; шесть — да.
    _raw_invoice(5, st.AWAITING_DOCS, requested=_local(5, time(0, 0, 1)))
    _raw_invoice(6, st.AWAITING_DOCS, requested=_local(6, time(23, 59)))
    # Без даты запроса (строку правили руками) — отсчёт от последней правки.
    _raw_invoice(7, st.AWAITING_DOCS, updated=timezone.now() - LONG_AGO)
    # Не в счёт: другие статусы и технические строки переноса из contracts.
    for n, status in enumerate((st.DRAFT, st.RETURNED, st.NOT_PAYABLE, st.PAID,
                                st.DOCS_PROVIDED, st.CLOSED, st.CANCELLED, st.REPLACED),
                               start=10):
        _raw_invoice(n, status, requested=_local(30, time(12)))
    _raw_invoice(20, st.UNDER_REVIEW, migrated=True)
    _raw_invoice(21, st.TO_PAY, migrated=True)
    _raw_invoice(22, st.AWAITING_DOCS, migrated=True, requested=_local(30, time(12)))

    assert _invoice_values() == (2, 2, 2)


def test_empty_invoice_queues_are_zero_not_absent(company_context):
    assert _invoice_values() == (0, 0, 0)


@pytest.mark.parametrize(("today", "requested", "overdue"), [
    # Пн 28.09.2026: запрос в среду 23.09 — пять календарных дней, ещё нет.
    (date(2026, 9, 28), datetime(2026, 9, 23, 23, 59), False),
    (date(2026, 9, 28), datetime(2026, 9, 22, 23, 59), True),
    # Выходные считаются: дни календарные, а не рабочие.
    (date(2026, 10, 5), datetime(2026, 9, 30, 9, 0), False),
    (date(2026, 10, 5), datetime(2026, 9, 29, 18, 0), True),
])
def test_closing_docs_threshold_counts_calendar_days(today, requested, overdue):
    now = timezone.make_aware(datetime.combine(today, time(8)))
    since = timezone.make_aware(requested)
    assert (since < metrics._docs_overdue_before(now)) is overdue


# ── веер по компаниям (Review Focus 5) ───────────────────────────────────

def _by_company(collected: dict, name: str) -> dict:
    spec = collected["bpp"][name]
    assert spec["labels"][0] == "company"
    return {labels[0]: number for labels, number in spec["values"]}


def test_bpp_off_at_one_company_does_not_stop_the_others(two_company_schemas):
    from apps.core import metrics as business

    alpha, beta = two_company_schemas
    for slug in (alpha, beta):
        with use_company(slug):
            check.run()
    CompanyModule.objects.create(company=Company.objects.get(slug=alpha), app_label="bpp",
                                 enabled=False)
    cache.clear()

    collected = business.collect_all()      # строгий режим: упади сбор — тест красный

    assert set(_by_company(collected, "bpp_requests_in_approval")) == {alpha, beta}
    # Ночная задача у компании с выключенным модулем не идёт — её итог не
    # экспортируется, иначе возраст дорос бы до ложного «сверка встала».
    assert set(_by_company(collected, "bpp_committed_check_age_seconds")) == {beta}
    assert _by_company(collected, "bpp_committed_mismatches") == {beta: 0}
