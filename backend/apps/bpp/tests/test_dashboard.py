"""Дашборд D-01 «Оплаты» (ТЗ §11.5, REQ-018; план этапа 4 A, задача 5 — A4.3).

Счета здесь заводятся строками модели напрямую, а не потоком B (заявка →
счёт → ФД → БУХ): дашборд только читает, ему важны статус, статус сверки,
«Оплачено по банку», отметки БУХ и сопоставления выписки — а поток на
десяток счетов в каждом тесте стоил бы минут. Статус сверки и сопоставления
ставятся руками: их пишет сверка (задачи 2–3), а здесь проверяется не она,
а что дашборд и реестр по ссылке считают одно и то же.

Главный сторож — ``test_each_indicator_equals_the_registry_count_by_its_link``:
у каждого показателя по счетам ``total`` реестра по его ссылке равен числу на
карточке — без фильтров, с фильтрами и с периодом по дате платежа.
"""

from __future__ import annotations

import itertools
import uuid
from datetime import timedelta
from decimal import Decimal
from urllib.parse import parse_qsl, urlsplit

import pytest
from django.test import Client
from django.utils import timezone

from apps.bpp.models import (
    BankImport,
    BankImportStatus,
    BankStatementLine,
    Invoice,
    InvoiceStatus,
    LineMatchStatus,
    OrgBankAccount,
    PaymentMark,
    PaymentMatch,
    PaymentMatchState,
    ReconStatus,
    StatementTemplate,
)
from apps.bpp.services.bank import recon
from apps.bpp.services.budget import committed as committed_calc
from apps.bpp.services.dashboard import payments as dashboard
from apps.bpp.services.invoices.read import working_days_before
from apps.bpp.tests import stage2 as s
from apps.bpp.tests import test_invoices as invoice_flow
from apps.bpp.tests.bank import common

pytestmark = pytest.mark.django_db
BASE = "/api/bpp/v1"
URL = f"{BASE}/dashboard/payments"
GD, BUH = invoice_flow.GD, invoice_flow.BUH
D = Decimal

_numbers = itertools.count(1)
_regs = itertools.count(1)


def _cp(name: str | None = None):
    reg = f"7{next(_regs):011d}"
    return invoice_flow._counterparty(reg, **({"name": name} if name else {}))


def _inv(status: str, amount, *, recon: str = ReconStatus.NO_DATA, paid_bank=0,
         currency: str = "KZT", rate=None, cp=None, project_id=None, article_id=None,
         author_id: int = s.SN) -> Invoice:
    amount = D(str(amount))
    rate = D(str(rate)) if rate is not None else None
    return Invoice.objects.create(
        number=f"СЧ-2026-9{next(_numbers):05d}", project_id=project_id or PROJECT,
        article_id=article_id or ARTICLE, counterparty=cp, ext_number=str(next(_numbers)),
        ext_date=timezone.localdate(), amount=amount, currency_code=currency, rate=rate,
        # Как ``invoices.recalc``: тенге — сама сумма, валюта без курса — пусто.
        amount_kzt=(amount if currency == "KZT"
                    else (amount * rate).quantize(D("0.01")) if rate else None),
        status=status, recon_status=recon, paid_bank_amount=D(str(paid_bank)),
        author_id=author_id)


def _mark(inv: Invoice, pay_date, amount=None, *, cancelled: bool = False) -> PaymentMark:
    return PaymentMark.objects.create(
        invoice=inv, pay_date=pay_date, amount=amount or inv.amount, marked_by_id=BUH,
        cancelled_at=timezone.now() if cancelled else None)


PROJECT, OTHER_PROJECT = uuid.uuid4(), uuid.uuid4()
ARTICLE = uuid.uuid4()


class _Statement:
    """Одна загрузка выписки «Сверена» — под строки и сопоставления."""

    def __init__(self):
        template = StatementTemplate.objects.create(name="CSV банка", format="csv")
        self.account = OrgBankAccount.objects.create(iban=common.iban(next(_regs)),
                                                     bic="HSBKKZKX", template=template)
        today = timezone.localdate()
        self.imp = BankImport.objects.create(
            number=f"ВП-2026-{next(_numbers):04d}", account=self.account, format="csv",
            period_from=today - timedelta(days=90), period_to=today,
            status=BankImportStatus.RECONCILED)
        self.rows = itertools.count(1)

    def line(self, amount, day, *, status=LineMatchStatus.MATCHED, bin_: str = "",
             cancelled: bool = False, currency: str = "KZT") -> BankStatementLine:
        return BankStatementLine.objects.create(
            bank_import=self.imp, account=self.account, row_no=next(self.rows), doc_date=day,
            doc_number=str(next(_numbers)), amount=D(str(amount)), recipient_bin=bin_,
            currency=currency,
            dedup_hash=uuid.uuid4().hex, match_status=status,
            cancelled_at=timezone.now() if cancelled else None)

    def pay(self, inv: Invoice, amount, day, *, state=PaymentMatchState.ACTIVE):
        line = self.line(amount, day)
        return PaymentMatch.objects.create(line=line, invoice=inv, amount=D(str(amount)),
                                           state=state)


def _get(slug, user_id, code, url=URL, **params):
    s.grant(slug, user_id, code)
    return Client().get(url, data=params, **s.auth(slug, user_id))


def _world(slug) -> dict:
    """Счета во всех состояниях, которые различают показатели."""
    today = timezone.localdate()
    stale_day = working_days_before(today, dashboard.BANK_WAIT_WORKING_DAYS + 1)
    w = {
        "fd": _inv(InvoiceStatus.UNDER_REVIEW, 100),
        "to_pay": _inv(InvoiceStatus.TO_PAY, 200),
        "partial": _inv(InvoiceStatus.PARTIALLY_PAID, 300),
        "stale": _inv(InvoiceStatus.PAID, 400),
        "fresh": _inv(InvoiceStatus.PAID, 500),
        "docs": _inv(InvoiceStatus.AWAITING_DOCS, 600),
        "full": _inv(InvoiceStatus.PAID, 700, recon=ReconStatus.FULL, paid_bank=700),
        "under": _inv(InvoiceStatus.PAID, 800, recon=ReconStatus.PARTIAL, paid_bank=760),
        "over": _inv(InvoiceStatus.CLOSED, 900, recon=ReconStatus.OVERPAID, paid_bank=925),
        "no_mark": _inv(InvoiceStatus.TO_PAY, 1000, recon=ReconStatus.PARTIAL, paid_bank=50),
        "other_project": _inv(InvoiceStatus.UNDER_REVIEW, 1100, project_id=OTHER_PROJECT),
        "draft": _inv(InvoiceStatus.DRAFT, 1200),
    }
    _mark(w["partial"], today, 100)
    _mark(w["stale"], stale_day)
    _mark(w["fresh"], today)
    _mark(w["docs"], stale_day - timedelta(days=7))
    for key in ("full", "under", "over"):
        _mark(w[key], today)
    # Выписка: «полностью» и «переплата» оплачены сегодня, недоплата и
    # «отметки нет» — месяц назад (вне периода «эта неделя»).
    bank = _Statement()
    bank.pay(w["full"], 700, today)
    bank.pay(w["over"], 925, today)
    bank.pay(w["under"], 760, today - timedelta(days=30))
    bank.pay(w["no_mark"], 50, today - timedelta(days=30))
    bank.line(33, today, status=LineMatchStatus.UNMATCHED)
    bank.line(44, today - timedelta(days=30), status=LineMatchStatus.UNMATCHED)
    w["bank"] = bank
    return w


def _by_key(payload) -> dict:
    return {row["key"]: row for row in payload["indicators"]}


# ── показатели и ссылки ─────────────────────────────────────────────────

def _check_links(slug, params: dict) -> dict:
    response = _get(slug, s.FD, "bpp-fd", **params)
    assert response.status_code == 200, response.content
    indicators = _by_key(response.json())
    client = Client()
    for key, row in indicators.items():
        if key == "unmatched":
            assert row["link"].startswith(dashboard.BANK_URL)
            continue
        link = urlsplit(row["link"])
        assert link.path == dashboard.REGISTRY_URL, row
        registry = client.get(f"{BASE}/invoices?{link.query}", **s.auth(slug, s.FD))
        assert registry.status_code == 200, (key, registry.content)
        assert registry.json()["total"] == row["count"], (key, row["link"])
        if key not in ("underpaid", "overpaid"):
            assert D(str(registry.json()["totals"]["amount_kzt"])) == D(str(row["amount"])), key
    return indicators


def test_each_indicator_equals_the_registry_count_by_its_link(company_context):
    slug = company_context["slug"]
    _world(slug)

    plain = _check_links(slug, {})
    assert {key: row["count"] for key, row in plain.items()} == {
        "fd": 2, "to_pay": 3, "awaiting_docs": 1, "bank_unconfirmed": 2, "full": 1,
        "underpaid": 2, "overpaid": 1, "no_mark": 1, "unmatched": 2}
    assert D(str(plain["fd"]["amount"])) == D("1200.00")

    # Фильтр проекта уходит в каждую ссылку.
    by_project = _check_links(slug, {"project_id": str(OTHER_PROJECT)})
    assert by_project["fd"]["count"] == 1 and by_project["to_pay"]["count"] == 0

    # Период — только у банковских показателей и по дате платежа; очереди — нет.
    today = timezone.localdate()
    week = {"period_from": (today - timedelta(days=6)).isoformat(),
            "period_to": today.isoformat()}
    period = _check_links(slug, week)
    assert {key: period[key]["count"] for key in
            ("fd", "to_pay", "full", "underpaid", "overpaid", "no_mark", "unmatched")} == {
        "fd": 2, "to_pay": 3, "full": 1, "underpaid": 0, "overpaid": 1, "no_mark": 0,
        "unmatched": 1}
    assert "bank_date_from=" in period["full"]["link"]
    assert "bank_date_from=" not in period["fd"]["link"]


def test_no_mark_link_uses_status_and_recon_filters(company_context):
    slug = company_context["slug"]
    _world(slug)
    indicators = _by_key(_get(slug, s.FD, "bpp-fd").json())
    query = parse_qsl(urlsplit(indicators["no_mark"]["link"]).query)
    assert "tab" not in dict(query)
    assert sorted(v for k, v in query if k == "recon_status") == ["full", "overpaid", "partial"]
    statuses = {v for k, v in query if k == "status"}
    assert statuses and not statuses & set(dashboard.PAID_GROUP)


def test_underpaid_and_overpaid_sums(company_context):
    slug = company_context["slug"]
    _world(slug)
    # Счёт в долларах: переплата 2 USD по курсу счёта 500 — 1 000,00 KZT.
    _inv(InvoiceStatus.PAID, 10, currency="USD", rate=500, recon=ReconStatus.OVERPAID,
         paid_bank=12)
    # «Частично» с Σ оплат больше суммы в недоплату не идёт отрицательным числом.
    _inv(InvoiceStatus.PAID, 10, recon=ReconStatus.PARTIAL, paid_bank=10)
    # Валюта без курса — не тенге: в число входит, в KZT-сумму нет (как
    # ``amount_kzt`` пустой у счёта без курса НБРК).
    _inv(InvoiceStatus.PAID, 10, currency="USD", recon=ReconStatus.OVERPAID, paid_bank=15)

    indicators = _by_key(dashboard.dashboard(invoice_flow._fd(slug), dashboard.Filters()))

    # 800 − 760 = 40; 1000 − 50 = 950; 10 − 10 = 0.
    assert indicators["underpaid"]["count"] == 3
    assert indicators["underpaid"]["amount"] == D("990.00")
    # 925 − 900 = 25; (12 − 10) × 500 = 1 000.
    assert indicators["overpaid"]["count"] == 3
    assert indicators["overpaid"]["amount"] == D("1025.00")


def test_bank_unconfirmed_counts_three_working_days(company_context):
    slug = company_context["slug"]
    today = timezone.localdate()
    edge = working_days_before(today, 3)
    older = working_days_before(today, 4)
    on_edge = _inv(InvoiceStatus.PAID, 100)
    _mark(on_edge, edge)
    stale = _inv(InvoiceStatus.PAID, 200)
    _mark(stale, older)
    # Последняя отметка — сегодняшняя: банк ждут меньше трёх дней.
    newer = _inv(InvoiceStatus.PAID, 300)
    _mark(newer, older, 150)
    _mark(newer, today, 150)
    # Сегодняшняя отметка отменена — последняя неотменённая старая.
    cancelled = _inv(InvoiceStatus.PAID, 400)
    _mark(cancelled, today, cancelled=True)
    _mark(cancelled, older)
    # Банк подтвердил — не в показателе, хоть отметка и старая.
    confirmed = _inv(InvoiceStatus.PAID, 500, recon=ReconStatus.FULL, paid_bank=500)
    _mark(confirmed, older)

    row = _by_key(dashboard.dashboard(invoice_flow._fd(slug), dashboard.Filters()))[
        "bank_unconfirmed"]

    assert row["count"] == 2 and row["amount"] == D("600.00")
    assert "bank_wait_days=3" in row["link"]


def test_working_days_before_skips_weekends():
    from datetime import date

    monday = date(2026, 9, 28)
    assert working_days_before(monday, 1) == date(2026, 9, 25)
    assert working_days_before(monday, 3) == date(2026, 9, 23)
    assert working_days_before(date(2026, 9, 30), 3) == date(2026, 9, 25)


# ── графики ─────────────────────────────────────────────────────────────

def test_article_chart_limit_committed_paid_fact(company_context):
    slug = company_context["slug"]
    s.user(s.SN)
    proj = s.project(members=[s.SN])
    s.approved_budget(slug, proj, {s.metal(): 1000, s.design(): 500})
    s.request_route()
    sn = s.actor(slug, s.SN, "bpp-sn")
    invoice_flow._approved_request(sn, proj, 300)
    # Оплата по банку по счёту статьи «Металлопрокат»: 120 подтверждено,
    # 80 «на проверке» — в «Оплачено факт» только 120.
    paid = _inv(InvoiceStatus.PAID, 200, project_id=proj.id, article_id=s.metal().id)
    bank = _Statement()
    bank.pay(paid, 120, timezone.localdate())
    bank.pay(paid, 80, timezone.localdate(), state=PaymentMatchState.REVIEW)

    rows = dashboard.article_chart(proj.id, actor=invoice_flow._fd(slug))

    committed = committed_calc.committed_by_article(proj.id)
    # Порядок — по коду статьи: T-DESIGN, T-METAL.
    assert [(r["name"], r["limit"], r["committed"]) for r in rows] == [
        ("Проектные работы", D("500.00"), D("0.00")),
        ("Металлопрокат", D("1000.00"), committed[str(s.metal().id)]),
    ]
    assert committed[str(s.metal().id)] == D("300.00")
    # «Оплачено факт» (CALC-007) — ``recon.paid_fact_by_article``.
    assert [r["paid_fact"] for r in rows] == [D("0.00"), D("120.00")]
    # Снабженец видит только статьи своей группы (BR-010).
    assert [r["name"] for r in dashboard.article_chart(proj.id, actor=sn)] == ["Металлопрокат"]
    # Без проекта и без бюджета — пусто.
    fd = invoice_flow._fd(slug)
    assert dashboard.article_chart(None, actor=fd) == []
    assert dashboard.article_chart(uuid.uuid4(), actor=fd) == []


def test_paid_fact_by_article_counts_only_confirmed_matches(company_context):
    """CALC-007, D-S4-1: Σ только действующих сопоставлений по счетам статьи
    проекта; «на проверке», отменённые, строки отменённые и строки отменённой
    загрузки не входят. Статья счёта — ``Invoice.article_id``."""
    project, other = uuid.uuid4(), uuid.uuid4()
    metal, design, empty = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    today = timezone.localdate()
    bank = _Statement()

    first = _inv(InvoiceStatus.PAID, 1000, project_id=project, article_id=metal)
    bank.pay(first, 100, today)
    bank.pay(first, 200, today, state=PaymentMatchState.REVIEW)
    bank.pay(first, 300, today, state=PaymentMatchState.CANCELLED)
    PaymentMatch.objects.create(line=bank.line(400, today, cancelled=True), invoice=first,
                                amount=D("400"))
    dropped = _Statement()
    BankImport.objects.filter(pk=dropped.imp.pk).update(status=BankImportStatus.CANCELLED)
    dropped.pay(first, 500, today)

    second = _inv(InvoiceStatus.CLOSED, 50, project_id=project, article_id=metal)
    bank.pay(second, 50.5, today)
    third = _inv(InvoiceStatus.PARTIALLY_PAID, 100, project_id=project, article_id=design)
    bank.pay(third, 70, today)
    only_review = _inv(InvoiceStatus.PAID, 100, project_id=project, article_id=empty)
    bank.pay(only_review, 100, today, state=PaymentMatchState.REVIEW)
    elsewhere = _inv(InvoiceStatus.PAID, 999, project_id=other, article_id=metal)
    bank.pay(elsewhere, 999, today)

    assert recon.paid_fact_by_article(project) == {str(metal): D("150.50"),
                                                   str(design): D("70.00")}
    assert recon.paid_fact_by_article(uuid.uuid4()) == {}


def test_unmatched_link_only_for_bank_viewers_and_amount_in_kzt(company_context):
    """Ссылка «Несопоставленные списания» — экран выписок, его видят ФД и БУХ
    (``bpp.bank`` view); ГД — число без ссылки. Строка в валюте — по курсу НБРК
    на дату платежа; нет курса — в сумму не входит, в число входит."""
    from apps.refdata.models import ExchangeRate

    slug = company_context["slug"]
    today = timezone.localdate()
    ExchangeRate.objects.update_or_create(currency_code="USD", on_date=today,
                                          defaults={"rate": D("500"), "source": "nbrk"})
    bank = _Statement()
    bank.line(100, today, status=LineMatchStatus.UNMATCHED)
    bank.line(2, today, status=LineMatchStatus.UNMATCHED, currency="USD")
    bank.line(7, today, status=LineMatchStatus.UNMATCHED, currency="EUR")   # курса нет
    bank.line(55, today, status=LineMatchStatus.EXCLUDED)

    fd = invoice_flow._fd(slug)
    fd_row = _by_key(dashboard.dashboard(fd, dashboard.Filters()))["unmatched"]
    assert fd_row["count"] == 3 and fd_row["amount"] == D("1100.00")
    # Реестр загрузок понимает только период — других параметров в ссылке нет.
    assert fd_row["link"] == "/bpp/bank"
    week = dashboard.Filters(period_from=today - timedelta(days=6), period_to=today)
    assert _by_key(dashboard.dashboard(fd, week))["unmatched"]["link"] == (
        f"/bpp/bank?period_from={week.period_from.isoformat()}&period_to={today.isoformat()}")
    only_to = dashboard.Filters(period_to=today)
    assert _by_key(dashboard.dashboard(fd, only_to))["unmatched"]["link"] == (
        f"/bpp/bank?period_to={today.isoformat()}")

    gd = s.actor(slug, GD, "bpp-gd")
    assert _by_key(dashboard.dashboard(gd, week))["unmatched"]["link"] is None


def _switch_off(company_id, name):
    from django.core.cache import cache

    from apps.companies.models import CompanyModule

    CompanyModule.objects.create(company_id=company_id, app_label=name, enabled=False)
    cache.clear()          # рубильник кэшируется на 5 с


def test_invoices_off_drops_invoice_indicators_and_charts(company_context):
    slug = company_context["slug"]
    _world(slug)
    _switch_off(company_context["id"], "bpp_invoices")

    body = dashboard.dashboard(invoice_flow._fd(slug),
                               dashboard.Filters(period_from=timezone.localdate(),
                                                 period_to=timezone.localdate()))

    assert [row["key"] for row in body["indicators"]] == ["unmatched"]
    assert body["weekly_paid"] == [] and body["top_counterparties"] == []
    # Экран пишет «подмодуль выключен», а не «данных нет»; авторов нет — фильтр не нужен.
    assert body["sections"] == {"invoices": False, "bank": True, "budget": True}
    assert body["authors"] == []


def test_bank_off_drops_bank_indicators_charts_and_paid_fact(company_context):
    slug = company_context["slug"]
    _world(slug)
    s.user(s.SN)
    proj = s.project(members=[s.SN])
    s.approved_budget(slug, proj, {s.metal(): 1000})
    _switch_off(company_context["id"], "bpp_bank")
    fd = invoice_flow._fd(slug)

    body = dashboard.dashboard(fd, dashboard.Filters())

    assert [row["key"] for row in body["indicators"]] == ["fd", "to_pay", "awaiting_docs"]
    assert body["weekly_paid"] == [] and body["top_counterparties"] == []
    assert body["sections"] == {"invoices": True, "bank": False, "budget": True}
    rows = dashboard.article_chart(proj.id, actor=fd)
    assert [row["paid_fact"] for row in rows] == [None]


def test_budget_off_drops_article_chart_and_says_so(company_context):
    slug = company_context["slug"]
    s.user(s.SN)
    proj = s.project(members=[s.SN])
    s.approved_budget(slug, proj, {s.metal(): 1000})
    fd = invoice_flow._fd(slug)
    assert dashboard.dashboard(fd, dashboard.Filters(project_id=str(proj.id)))["article_chart"]
    _switch_off(company_context["id"], "bpp_budget")

    body = dashboard.dashboard(fd, dashboard.Filters(project_id=str(proj.id)))

    assert body["article_chart"] == []
    assert body["sections"] == {"invoices": True, "bank": True, "budget": False}


# ── авторы (фильтр «Автор счёта») ───────────────────────────────────────

def test_authors_are_invoice_authors_visible_to_the_actor(company_context):
    """Список фильтра «Автор счёта» — из счетов реестра, а не из кадров: у
    ролей дашборда нет прав ``hr``. Видимость — реестра (СН — только свои),
    остальные фильтры дашборда список не сужают; автора без учётки — ``name:
    null``. Перенесённый из «Договоров» счёт виден в реестре с пометкой
    (D-B61-8) — и его автор в списке."""
    slug = company_context["slug"]
    s.user(s.SN, "snab")
    s.user(s.PM, "arman")
    _inv(InvoiceStatus.UNDER_REVIEW, 100, author_id=s.SN)
    _inv(InvoiceStatus.TO_PAY, 200, author_id=s.SN, project_id=OTHER_PROJECT)
    _inv(InvoiceStatus.DRAFT, 300, author_id=s.PM)
    _inv(InvoiceStatus.PAID, 400, author_id=99901)            # учётки нет
    Invoice.objects.filter(pk=_inv(InvoiceStatus.PAID, 500, author_id=s.SN2).pk).update(
        is_migrated=True)                          # перенесённый — в реестре (D-B61-8)
    fd = invoice_flow._fd(slug)
    expected = [{"id": s.PM, "name": "Тест Arman"}, {"id": s.SN, "name": "Тест Snab"},
                {"id": s.SN2, "name": None}, {"id": 99901, "name": None}]

    assert dashboard.authors(fd) == expected
    narrowed = dashboard.Filters(project_id=str(OTHER_PROJECT), author_id=s.SN)
    assert dashboard.dashboard(fd, narrowed)["authors"] == expected

    sn = s.actor(slug, s.SN, "bpp-sn")
    assert dashboard.authors(sn) == [{"id": s.SN, "name": "Тест Snab"}]

    response = _get(slug, s.FD, "bpp-fd")
    assert response.status_code == 200, response.content
    assert response.json()["authors"] == expected


def test_top10_ties_are_ordered_by_name(company_context):
    slug = company_context["slug"]
    today = timezone.localdate()
    bank = _Statement()
    for name in ("ТОО «Бета»", "ТОО «Альфа»"):
        inv = _inv(InvoiceStatus.PAID, 100, cp=_cp(name), recon=ReconStatus.FULL,
                   paid_bank=100)
        bank.pay(inv, 100, today)

    top = dashboard.top_counterparties(invoice_flow._fd(slug), dashboard.Filters())

    assert [row["name"] for row in top] == ["ТОО «Альфа»", "ТОО «Бета»"]


def test_weekly_and_top10(company_context):
    slug = company_context["slug"]
    today = timezone.localdate()
    monday = today - timedelta(days=today.weekday())
    bank = _Statement()
    cps = [_cp(f"ТОО «Поставщик {n:02d}»") for n in range(12)]
    for n, cp in enumerate(cps):
        inv = _inv(InvoiceStatus.PAID, 1000 + n, cp=cp, recon=ReconStatus.FULL,
                   paid_bank=1000 + n)
        bank.pay(inv, 1000 + n, today)
    # Две недели назад — ещё 5 000 первому; отменённое и «на проверке» не в счёт.
    inv = _inv(InvoiceStatus.PAID, 5000, cp=cps[0], recon=ReconStatus.FULL, paid_bank=5000)
    bank.pay(inv, 5000, monday - timedelta(days=14))
    bank.pay(inv, 777, today, state=PaymentMatchState.REVIEW)
    bank.pay(inv, 888, today, state=PaymentMatchState.CANCELLED)
    # Долларовый счёт: 10 USD по курсу счёта 500 — 5 000,00 KZT.
    usd = _inv(InvoiceStatus.PAID, 10, currency="USD", rate=500, cp=cps[1],
               recon=ReconStatus.FULL, paid_bank=10)
    bank.pay(usd, 10, today)

    fd = invoice_flow._fd(slug)
    period = dashboard.Filters(period_from=monday - timedelta(days=14), period_to=today)
    weeks = dashboard.weekly_paid(fd, period)
    this_week = sum(D(1000 + n) for n in range(12)) + D("5000.00")
    assert weeks == [
        {"week_start": monday - timedelta(days=14), "amount": D("5000.00")},
        {"week_start": monday - timedelta(days=7), "amount": D("0.00")},
        {"week_start": monday, "amount": this_week},
    ]

    top = dashboard.top_counterparties(fd, period)
    assert len(top) == 10
    assert [row["counterparty_id"] for row in top[:2]] == [str(cps[1].pk), str(cps[0].pk)]
    assert top[0]["amount"] == D("6001.00") and top[1]["amount"] == D("6000.00")
    assert top[-1]["amount"] == D("1004.00")

    # Контрагент в фильтре — только его платежи.
    only = dashboard.top_counterparties(
        fd, dashboard.Filters(counterparty_id=str(cps[5].pk)))
    assert only == [{"counterparty_id": str(cps[5].pk), "name": "ТОО «Поставщик 05»",
                     "amount": D("1005.00")}]


# ── права и параметры ───────────────────────────────────────────────────

@pytest.mark.parametrize("user_id,code", [(s.FD, "bpp-fd"), (GD, "bpp-gd"), (BUH, "bpp-buh")])
def test_dashboard_roles_by_matrix(company_context, user_id, code):
    slug = company_context["slug"]
    response = _get(slug, user_id, code)
    assert response.status_code == 200, response.content
    body = response.json()
    assert [row["key"] for row in body["indicators"]] == [
        "fd", "to_pay", "awaiting_docs", "bank_unconfirmed", "full", "underpaid",
        "overpaid", "no_mark", "unmatched"]
    assert body["article_chart"] == [] and body["weekly_paid"] == []
    assert body["sections"] == {"invoices": True, "bank": True, "budget": True}
    assert body["authors"] == []


def test_supplier_gets_403(company_context):
    slug = company_context["slug"]
    response = _get(slug, s.SN, "bpp-sn")
    assert response.status_code == 403
    assert response.json()["code"] == "E-ACC-01"


@pytest.mark.parametrize("params,field", [
    ({"period_from": "30.09.2026"}, "period_from"),
    ({"period_from": "2026-09-30", "period_to": "2026-09-01"}, "period_to"),
    ({"project_id": "abc"}, "project_id"),
    ({"author_id": "x"}, "author_id"),
    # 1828 дней — длиннее 5 лет (``MAX_PERIOD_DAYS`` = 1827).
    ({"period_from": "2020-01-01", "period_to": "2025-01-02"}, "period_to"),
])
def test_bad_params_are_422(company_context, params, field):
    slug = company_context["slug"]
    response = _get(slug, s.FD, "bpp-fd", **params)
    assert response.status_code == 422, response.content
    assert response.json()["fields"][0]["field"] == field



def test_five_year_period_is_the_limit_and_open_periods_do_not_explode(company_context):
    """Предел периода (M-c): ровно 5 лет — 200 и недели нулями по всему
    периоду; открытая с одной стороны граница на краю календаря не роняет
    ручку (``OverflowError`` у 9999-12-27) и не рисует сотни тысяч нулевых
    недель — только недели с платежами."""
    from datetime import date

    slug = company_context["slug"]
    ok = _get(slug, s.FD, "bpp-fd", period_from="2020-01-01", period_to="2025-01-01")
    assert ok.status_code == 200, ok.content
    weeks = ok.json()["weekly_paid"]
    assert (weeks[0]["week_start"], weeks[-1]["week_start"], len(weeks)) == (
        "2019-12-30", "2024-12-30", 262)

    today = timezone.localdate()
    monday = today - timedelta(days=today.weekday())
    inv = _inv(InvoiceStatus.PAID, 100, recon=ReconStatus.FULL, paid_bank=100)
    _Statement().pay(inv, 100, today)
    fd = invoice_flow._fd(slug)
    for filters in (dashboard.Filters(period_from=date(1, 1, 1)),
                    dashboard.Filters(period_to=date(9999, 12, 31))):
        assert dashboard.weekly_paid(fd, filters) == [
            {"week_start": monday, "amount": D("100.00")}], filters
    for params in ({"period_from": "0001-01-01"}, {"period_to": "9999-12-31"}):
        response = _get(slug, s.FD, "bpp-fd", **params)
        assert response.status_code == 200, (params, response.content)


def test_unmatched_counterparty_filter_compares_bin_normalised(company_context):
    """Фильтр контрагента у «Не сопоставлено» (M-d) сравнивает БИН так же, как
    автосверка и кандидаты: без пробелов и регистра с обеих сторон."""
    slug = company_context["slug"]
    today = timezone.localdate()
    cp = _cp()
    reg = cp.reg_number
    foreign = invoice_flow._counterparty("AB123", country_code="GB", name="Foreign Ltd")
    bank = _Statement()
    bank.line(10, today, status=LineMatchStatus.UNMATCHED, bin_=f"{reg[:4]} {reg[4:8]} {reg[8:]}")
    bank.line(20, today, status=LineMatchStatus.UNMATCHED, bin_=reg)
    bank.line(40, today, status=LineMatchStatus.UNMATCHED, bin_="999999999999")
    bank.line(80, today, status=LineMatchStatus.UNMATCHED, bin_="ab 123")

    fd = invoice_flow._fd(slug)
    row = _by_key(dashboard.dashboard(
        fd, dashboard.Filters(counterparty_id=str(cp.pk))))["unmatched"]
    assert (row["count"], row["amount"]) == (2, D("30.00"))
    row = _by_key(dashboard.dashboard(
        fd, dashboard.Filters(counterparty_id=str(foreign.pk))))["unmatched"]
    assert (row["count"], row["amount"]) == (1, D("80.00"))
