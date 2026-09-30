"""Жизненный цикл альтернатив и контракт выбора для B5.1 (ТЗ §12.2, §12.4
п.3, 6, 7, BR-096, AC-017; план этапа 5 A, задача 3, D-S5-6).

Закрытие АП идёт через настоящие действия B над исходным документом (решение
ФД, отмена счёта, голоса и отзыв договора) — хуки зоны B зовут
``lifecycle.close_for_source``. Гонка подачи с решением ФД (Review Focus 2) —
транзакционный тест на ORM-счёте в обоих порядках.
"""

from __future__ import annotations

import threading
import time
import uuid
from decimal import Decimal

import pytest
from django.core.cache import cache
from django.db import connection, transaction

from apps.bpp.models import AlternativeOffer, AuditLog, Invoice, InvoiceStatus, OfferStatus
from apps.bpp.services.agreements import agreements as agreement_service
from apps.bpp.services.alternatives import lifecycle, offers
from apps.bpp.services.invoices import decisions
from apps.bpp.services.invoices import invoices as invoice_service
from apps.bpp.services.money import fmt
from apps.bpp.tests import stage2 as s
from apps.bpp.tests.bank.common import counterparty as orm_counterparty
from apps.bpp.tests.bank.common import orm_invoice
from apps.bpp.tests.test_files import memory_storage  # noqa: F401  (фикстура)
from apps.companies.models import Company, CompanyMembership, CompanyModule
from apps.notifications import interface as notifications
from apps.signoff import interface as signoff
from htqweb.errors import DomainError

from . import common

D = Decimal
GD = 910  # второй этап маршрута договора (tests/test_invoices.py::_routes)
pytestmark = pytest.mark.django_db


def _fail(call) -> DomainError:
    with pytest.raises(DomainError) as exc:
        call()
    return exc.value


def _fd(slug):
    return s.actor(slug, s.FD, "bpp-fd")


def _fresh(offer) -> AlternativeOffer:
    return AlternativeOffer.objects.get(pk=offer.pk)


def _agr_decide(agr, user_id, decision="approve", comment=""):
    process = signoff.get_process_for("bpp.agreement", str(agr.pk))
    task = next(t for stage in process["stages"] for t in stage["tasks"]
                if t["user_id"] == user_id and t["state"] == "pending")
    result = signoff.decide_many(actor_id=user_id, items=[
        {"task_id": task["id"], "decision": decision, "comment": comment}])[0]
    assert result.get("ok"), result
    return result


def _events(slug, user_id, event) -> list[dict]:
    return [row for row in notifications.latest(user_id, company_slug=slug)
            if row["event"] == event]


# ── «Не выбрано» по решению без выбора, §12.4 п.6 ─────────────────────

def test_ac017_pay_sets_offers_not_selected(company_context):
    slug = company_context["slug"]
    _, _, inv = common.invoice_on_review(slug, 1000)
    first = common.filed(common.sn(slug, common.SN2), inv, common.cp(2), price=900)
    second = common.filed(common.sn(slug, common.SN3), inv, common.cp(3), price=800)
    draft = common.draft(common.sn(slug, common.SN4), inv)

    decisions.decide(_fd(slug), inv.id, decision="pay")

    for offer in (first, second):
        row = _fresh(offer)
        assert row.status == OfferStatus.NOT_SELECTED
        assert row.closed_reason == lifecycle.REASON_INVOICE_PAY
        assert AuditLog.objects.filter(object_id=str(offer.pk), action="not_selected").exists()
    assert _fresh(draft).status == OfferStatus.ANNULLED
    assert lifecycle.offers_for("invoice", inv.pk) == []
    (note,) = _events(slug, common.SN2, lifecycle.EVENT_CLOSED)
    assert note["title"] == (f"Альтернатива {first.number} к {inv.number}: «Не выбрано». "
                             f"{lifecycle.REASON_INVOICE_PAY}")
    assert note["url"] == f"/bpp/alternatives/{first.pk}"
    # Повтор ничего не меняет: закрывать уже нечего.
    assert lifecycle.close_for_source("invoice", inv.pk, lifecycle.NOT_SELECTED,
                                      reason="повтор") == 0
    with pytest.raises(ValueError):
        lifecycle.close_for_source("invoice", inv.pk, "selected", reason="нет такого исхода")


def test_agreement_approved_in_original_sets_not_selected(company_context):
    slug = company_context["slug"]
    _, _, agr = common.agreement_on_review(slug, 1000)
    offer = common.filed(common.sn(slug, common.SN2), agr, common.cp(2), price=900,
                         source_type=common.AGREEMENT)

    _agr_decide(agr, s.FD, "approve")
    assert _fresh(offer).status == OfferStatus.SUBMITTED  # голосование идёт
    _agr_decide(agr, GD, "approve")

    row = _fresh(offer)
    assert (row.status, row.closed_reason) == (OfferStatus.NOT_SELECTED,
                                               lifecycle.REASON_AGREEMENT_APPROVED)


# ── «Аннулировано», §12.4 п.7 ─────────────────────────────────────────

def _invoice_case(slug, action):
    author, _, inv = common.invoice_on_review(slug, 1000)
    runs = {
        "invoice_return": (lambda: decisions.decide(
            _fd(slug), inv.id, decision="return", comment="Уточните позиции счёта"),
            lifecycle.REASON_RETURNED),
        "invoice_not_payable": (lambda: decisions.decide(
            _fd(slug), inv.id, decision="not_payable", comment="Закупка больше не нужна"),
            lifecycle.REASON_INVOICE_NOT_PAYABLE),
        "invoice_cancel": (lambda: invoice_service.cancel(
            author, inv.id, expected_version=None, comment="Счёт выставлен ошибочно"),
            lifecycle.REASON_INVOICE_CANCELLED),
    }
    run, reason = runs[action]
    return inv, common.INVOICE, run, reason


def _agreement_case(slug, action):
    author, _, agr = common.agreement_on_review(slug, 1000)
    runs = {
        "agreement_reject": (lambda: _agr_decide(agr, s.FD, "reject", "Контрагент не подходит"),
                             lifecycle.REASON_AGREEMENT_REJECTED),
        "agreement_rework": (lambda: _agr_decide(agr, s.FD, "rework", "Уточните номер договора"),
                             lifecycle.REASON_RETURNED),
        "agreement_withdraw": (lambda: agreement_service.withdraw(
            author, agr.id, expected_version=None), lifecycle.REASON_AGREEMENT_WITHDRAWN),
    }
    run, reason = runs[action]
    return agr, common.AGREEMENT, run, reason


@pytest.mark.parametrize("action", [
    "invoice_return", "invoice_not_payable", "invoice_cancel",
    "agreement_reject", "agreement_rework", "agreement_withdraw",
])
def test_returned_rejected_cancelled_annul(company_context, action):
    slug = company_context["slug"]
    make = _invoice_case if action.startswith("invoice") else _agreement_case
    source, source_type, run, reason = make(slug, action)
    submitted = common.filed(common.sn(slug, common.SN2), source, common.cp(2), price=900,
                             source_type=source_type)
    draft = common.draft(common.sn(slug, common.SN3), source, source_type)

    run()

    for offer in (submitted, draft):
        row = _fresh(offer)
        assert (row.status, row.closed_reason) == (OfferStatus.ANNULLED, reason)
        assert AuditLog.objects.filter(object_id=str(offer.pk), action="annulled").exists()
    assert len(_events(slug, common.SN2, lifecycle.EVENT_CLOSED)) == 1
    assert len(_events(slug, common.SN3, lifecycle.EVENT_CLOSED)) == 1


def test_resubmitted_source_accepts_new_offers(company_context):
    slug = company_context["slug"]
    author, _, inv = common.invoice_on_review(slug, 1000)
    buyer = common.sn(slug, common.SN2)
    first = common.filed(buyer, inv, common.cp(2), price=900)
    decisions.decide(_fd(slug), inv.id, decision="return", comment="Уточните позиции счёта")
    assert _fresh(first).status == OfferStatus.ANNULLED
    assert _fail(lambda: common.draft(buyer, inv)).code == "E-STATE-01"

    invoice_service.submit(author, inv.id, expected_version=None)
    inv.refresh_from_db()
    assert inv.status == InvoiceStatus.UNDER_REVIEW and inv.fd_decided_at is not None
    assert offers.window_open(inv)

    again = common.filed(buyer, inv, first.counterparty, price=850)   # тот же контрагент — можно
    assert again.status == OfferStatus.SUBMITTED and again.pk != first.pk


# ── выбор, контракт B5.1 ───────────────────────────────────────────────

def test_mark_selected_closes_others_and_is_single(company_context):
    slug = company_context["slug"]
    _, _, inv = common.invoice_on_review(slug, 1000)
    chosen = common.filed(common.sn(slug, common.SN2), inv, common.cp(2), price=900)
    other = common.filed(common.sn(slug, common.SN3), inv, common.cp(3), price=800)
    draft = common.draft(common.sn(slug, common.SN4), inv)

    offer = lifecycle.mark_selected(chosen.pk, actor_id=s.FD, comment="Дешевле при том же сроке")

    assert offer.status == OfferStatus.SELECTED
    row = _fresh(chosen)
    assert (row.status, row.decided_by_id, row.decision_comment) == (
        OfferStatus.SELECTED, s.FD, "Дешевле при том же сроке")
    assert row.decided_at is not None
    assert (_fresh(other).status, _fresh(other).closed_reason) == (
        OfferStatus.NOT_SELECTED, f"Выбрана альтернатива {chosen.number}")
    assert _fresh(draft).status == OfferStatus.ANNULLED
    assert AuditLog.objects.filter(object_id=str(chosen.pk), action="selected").exists()
    assert len(_events(slug, common.SN2, lifecycle.EVENT_SELECTED)) == 1
    assert len(_events(slug, common.SN3, lifecycle.EVENT_CLOSED)) == 1

    for again in (chosen, other):   # BR-096: документ заменяется один раз
        err = _fail(lambda o=again: lifecycle.mark_selected(o.pk, actor_id=s.FD, comment="ещё"))
        assert (err.code, err.status, err.message) == (
            "E-STATE-01", 409, "Документ уже заменён альтернативой")


def test_mark_selected_needs_submitted_offer_and_open_window(company_context):
    slug = company_context["slug"]
    _, _, inv = common.invoice_on_review(slug, 1000)
    buyer = common.sn(slug, common.SN2)
    withdrawn = common.filed(buyer, inv, common.cp(2), price=900)
    offers.withdraw(buyer, withdrawn.id, expected_version=None)
    live = common.filed(common.sn(slug, common.SN3), inv, common.cp(3), price=800)

    err = _fail(lambda: lifecycle.mark_selected(withdrawn.pk, actor_id=s.FD, comment=""))
    assert (err.code, err.status, err.message) == ("E-STATE-01", 409, lifecycle.OPTION_GONE)
    assert _fail(lambda: lifecycle.mark_selected(uuid.uuid4(), actor_id=s.FD,
                                                 comment="")).status == 404

    Invoice.objects.filter(pk=inv.pk).update(status=InvoiceStatus.TO_PAY)
    err = _fail(lambda: lifecycle.mark_selected(live.pk, actor_id=s.FD, comment=""))
    assert (err.code, err.status) == ("E-STATE-01", 409)
    assert _fresh(live).status == OfferStatus.SUBMITTED


def test_mark_selected_offer_deleted_after_probe_is_404(company_context, monkeypatch):
    """M1: АП удалили между пробой и замком — 404, а не ``StopIteration`` (500)."""
    slug = company_context["slug"]
    _, _, inv = common.invoice_on_review(slug, 1000)
    gone = common.filed(common.sn(slug, common.SN2), inv, common.cp(2), price=900)
    real = offers.source_of

    def source_then_delete(*args, **kwargs):
        source = real(*args, **kwargs)
        AlternativeOffer.objects.filter(pk=gone.pk).delete()
        return source

    monkeypatch.setattr(lifecycle.offers, "source_of", source_then_delete)
    err = _fail(lambda: lifecycle.mark_selected(gone.pk, actor_id=s.FD, comment=""))
    assert (err.code, err.status) == ("E-NOT-FOUND", 404)


def test_options_for_agreement_lists_original_and_submitted(company_context):
    slug = company_context["slug"]
    _, _, agr = common.agreement_on_review(slug, 1000)
    first = common.filed(common.sn(slug, common.SN2), agr, common.cp(2), price=900,
                         source_type=common.AGREEMENT)
    second = common.filed(common.sn(slug, common.SN3), agr, common.cp(3), price=800,
                          source_type=common.AGREEMENT)
    gone_author = common.sn(slug, common.SN4)
    gone = common.filed(gone_author, agr, common.cp(4), price=700,
                        source_type=common.AGREEMENT)
    offers.withdraw(gone_author, gone.id, expected_version=None)
    common.draft(common.sn(slug, 923), agr, common.AGREEMENT)   # черновик — не вариант

    options = lifecycle.options_for("agreement", agr.pk)

    assert options == [
        {"key": "original", "label": f"Исходный документ {agr.number}"},
        *({"key": f"offer:{o.pk}",
           "label": f"Альтернатива {o.number} — ТОО «Альфа», {fmt(o.amount, o.currency_code)}"}
          for o in (first, second)),
    ]
    assert [o.pk for o in lifecycle.offers_for("agreement", agr.pk)] == [first.pk, second.pk]
    assert lifecycle.check_option("agreement", agr.pk, "original") is None
    assert lifecycle.check_option("agreement", agr.pk, f"offer:{first.pk}") is None
    for key in (f"offer:{gone.pk}", f"offer:{uuid.uuid4()}", "offer:не-ключ"):
        assert lifecycle.check_option("agreement", agr.pk, key) == lifecycle.OPTION_GONE
    assert lifecycle.check_option("agreement", uuid.uuid4(), f"offer:{first.pk}") == \
        lifecycle.OPTION_GONE
    assert lifecycle.check_option("agreement", agr.pk, "approve") == "Неизвестный вариант голоса"
    assert lifecycle.options_for("agreement", uuid.uuid4()) == []


# ── уведомление снабженцам, §12.2 ─────────────────────────────────────

def _people(slug):
    """Роли и членство: ``holders_of`` видит только участников компании."""
    company = Company.objects.get(slug=slug)
    for user_id, role in ((s.SN, "bpp-sn"), (common.SN2, "bpp-sn"), (common.SN3, "bpp-sn"),
                          (s.PM, "bpp-pm"), (s.FD, "bpp-fd")):
        s.grant(slug, user_id, role)
        CompanyMembership.objects.get_or_create(company=company, user_id=user_id)


def _window_titles(slug, user_id) -> list[str]:
    return [row["title"] for row in _events(slug, user_id, lifecycle.EVENT_WINDOW)]


def test_buyers_notified_on_source_start(company_context):
    slug = company_context["slug"]
    _people(slug)

    _, _, inv = common.invoice_on_review(slug, 1000)

    assert inv.initiator_role == "sn"
    expected = (f"СН U904 Т. отправил счёт {inv.number} на 1 000,00 KZT, ТОО «Альфа». "
                f"Можно предложить альтернативу")
    for buyer in (common.SN2, common.SN3):
        assert _window_titles(slug, buyer) == [expected]
    assert _window_titles(slug, s.SN) == []       # автор документа
    assert _window_titles(slug, s.PM) == []       # ПМ альтернатив не подаёт
    assert _window_titles(slug, s.FD) == []
    row = _events(slug, common.SN2, lifecycle.EVENT_WINDOW)[0]
    assert row["url"] == f"/bpp/alternatives?source=invoice:{inv.pk}"

    # ПМ — автор: уведомлены все СН, сам ПМ — нет.
    pm_invoice = orm_invoice(common.cp(2), 1000, status=InvoiceStatus.UNDER_REVIEW,
                             author_id=s.PM)
    pm_invoice.initiator_role = "pm"
    pm_invoice.save(update_fields=["initiator_role"])
    lifecycle.notify_buyers("invoice", pm_invoice.pk)
    pm_title = (f"ПМ U905 Т. отправил счёт {pm_invoice.number} на 1 000,00 KZT, ТОО «Альфа». "
                f"Можно предложить альтернативу")
    for buyer in (s.SN, common.SN2, common.SN3):
        assert pm_title in _window_titles(slug, buyer)
    assert _window_titles(slug, s.PM) == []


def test_agreement_start_notifies_and_switch_off_silences(company_context):
    slug = company_context["slug"]
    _people(slug)

    _, _, agr = common.agreement_on_review(slug, 1000)

    (title,) = _window_titles(slug, common.SN2)
    assert agr.amount is not None
    assert title.startswith(f"СН U904 Т. отправил договор {agr.number} на "
                            f"{fmt(agr.amount, agr.currency_code)}")
    assert title.endswith("Можно предложить альтернативу")

    CompanyModule.objects.create(company_id=company_context["id"],
                                 app_label="bpp_alternatives", enabled=False)
    cache.clear()          # рубильник кэшируется на 5 с
    lifecycle.notify_buyers("agreement", agr.pk)
    assert len(_window_titles(slug, common.SN2)) == 1


# ── подача против решения ФД, Review Focus 2 ──────────────────────────

@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("first", ["submit", "fd"])
def test_submit_vs_fd_decision_race(monkeypatch, first):
    """ФД ставит счёту «К оплате» (замок строки счёта + колбэк ``on_approved``,
    как у ``decisions.decide``), пока СН подаёт АП (замок той же строки).
    Первый держит замок, второй ждёт: подача первой — АП «Не выбрано»,
    решение первым — подача отклонена BR-090, черновик «Аннулировано».
    «Подано» к решённому счёту не остаётся ни в одном порядке."""
    monkeypatch.setattr(offers.core_files, "list_files", lambda owner: [{"id": "kp"}])
    inv = common.orm_invoice_source([1000], author_id=901)
    buyer = s.actor(None, 911, superuser=True)
    offer = common.fill(buyer, common.draft(buyer, inv), orm_counterparty("100000000002"),
                        price=D("900"), kp=False)

    locked = threading.Event()
    real = offers.source_of

    def gated(source_type, source_id, *, lock=False):
        source = real(source_type, source_id, lock=lock)
        if lock and first == "submit":
            locked.set()
            time.sleep(0.5)   # решение ФД успевает упереться в замок
        return source

    monkeypatch.setattr(offers, "source_of", gated)
    results: list = []
    crashes: list[str] = []
    guard = threading.Lock()

    def run(call):
        try:
            call()
            outcome = "ok"
        except DomainError as exc:
            outcome = (exc.code, exc.message)
        except Exception as exc:  # noqa: BLE001 — любой другой исход — провал
            with guard:
                crashes.append(repr(exc))
            return
        finally:
            connection.close()
        with guard:
            results.append(outcome)

    def submit():
        if first == "fd":
            locked.wait(timeout=10)
        offers.submit(buyer, offer.id, expected_version=None)

    def fd():
        if first == "submit":
            locked.wait(timeout=10)
        with transaction.atomic():
            invoice_service.lock(inv.pk)
            if first == "fd":
                locked.set()
                time.sleep(0.5)   # подача успевает упереться в замок
            invoice_service.on_approved(inv.pk)

    submitter = threading.Thread(target=run, args=(submit,))
    decider = threading.Thread(target=run, args=(fd,))
    for thread in (submitter, decider):
        thread.start()
    for thread in (submitter, decider):
        thread.join()

    assert crashes == []
    assert Invoice.objects.get(pk=inv.pk).status == InvoiceStatus.TO_PAY
    assert not AlternativeOffer.objects.filter(source_id=inv.pk,
                                               status=OfferStatus.SUBMITTED).exists()
    status = _fresh(offer).status
    if first == "submit":
        assert sorted(results, key=str) == ["ok", "ok"]
        assert status == OfferStatus.NOT_SELECTED
    else:
        assert ("E-STATE-01", "Документ уже решён — альтернатива не подаётся") in results
        assert status == OfferStatus.ANNULLED
