"""Счёт на оплату (ТЗ §10, §15.4, задача B3.2): порог 1000 МРП (AC-005),
остаток договора (AC-008), двойное «Оплатить» (AC-013), дубль (E-INV-03),
оплаты и их отмена (BR-052), закрывающие документы после оплаты (D-13),
массовое решение, страховка бюджета в общем инбоксе, дробление (D-17),
«Задействовано» (BR-043, CALC-002)."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.test import Client
from django.utils import timezone

from apps.bpp.interface import closing_docs_pending_for_user, find_by_number
from apps.bpp.models import (
    AuditLog,
    BudgetLine,
    Counterparty,
    Invoice,
    InvoiceStatus,
)
from apps.bpp.services.agreements import agreements as agreement_service
from apps.bpp.services.budget import committed as calc
from apps.bpp.services.invoices import decisions, payments, read
from apps.bpp.services.invoices import invoices as service
from apps.bpp.services.requests import requests as request_service
from apps.bpp.tests import stage2 as s
from apps.refdata.models import ExchangeRate
from apps.signoff import interface as signoff
from htqweb.errors import DomainError
from htqweb.tenancy.db import use_company

pytestmark = pytest.mark.django_db
GD, BUH = 910, 907
BASE = "/api/bpp/v1"


def _counterparty(reg: str = "100000000001", **over) -> Counterparty:
    fields = {"name": "ТОО «Альфа»", "kind": "legal", "country_code": "KZ", "reg_number": reg,
              "is_vat_payer": True, "verified_override": True, **over}
    return Counterparty.objects.create(**fields)


def _routes():
    for user_id in (s.FD, s.TD, s.OD, GD, BUH):
        s.user(user_id)
    signoff.configure_route(
        subject_type="bpp.invoice", name="Счёт: ФД",
        stages=[{"order": 1, "name": "ФД", "quorum": "any", "approver_kind": "users",
                 "user_ids": [s.FD], "requirement_key": "bpp:budget"}],
        flags={"reject_comment_min": 10})
    signoff.configure_route(
        subject_type="bpp.agreement", name="Договор",
        stages=[{"order": n, "name": name, "quorum": "any", "approver_kind": "users",
                 "user_ids": [uid]}
                for n, (name, uid) in enumerate((("ФД", s.FD), ("ГД", GD)), start=1)])


def _setup(slug, limit=20_000_000):
    s.user(s.SN)
    proj = s.project(members=[s.SN])
    s.approved_budget(slug, proj, {s.metal(): limit})
    s.request_route()
    _routes()
    return proj


def _approved_request(sn, proj, *amounts):
    req = request_service.create_draft(sn, {**s.header(proj, s.metal()),
                                            "items": s.items(*[(1, a) for a in amounts])})
    req = request_service.submit(sn, req.id, expected_version=None)
    s.decide(req, s.TD, "approve"), s.decide(req, s.OD, "approve")
    return req


def _invoice(slug, *amounts, counterparty=None, limit=20_000_000, ext_date=None,
             proj=None, sn=None):
    proj = proj or _setup(slug, limit)
    sn = sn or s.actor(slug, s.SN, "bpp-sn")
    req = _approved_request(sn, proj, *amounts)
    inv = service.create_from_plan(sn, [str(i.id) for i in req.items.all()])
    cp = counterparty or _counterparty()
    inv, _ = service.update_draft(sn, inv.id, expected_version=None, data={
        "counterparty_id": str(cp.pk), "ext_number": "145",
        "ext_date": ext_date or timezone.localdate()})
    return sn, proj, inv


def _submitted(slug, *amounts, **kwargs):
    sn, proj, inv = _invoice(slug, *amounts, **kwargs)
    return sn, proj, service.submit(sn, inv.id, expected_version=None)


def _code(call) -> str:
    with pytest.raises(DomainError) as exc:
        call()
    return exc.value.code


def _fd(slug):
    return s.actor(slug, s.FD, "bpp-fd")


def _buh(slug):
    return s.actor(slug, BUH, "bpp-buh")


# ── порог 1000 МРП, AC-005 ─────────────────────────────────────────────

def test_ac005_threshold_boundary(company_context):
    slug = company_context["slug"]
    sn, proj, ok = _invoice(slug, Decimal("4325000.00"), ext_date=date(2026, 9, 1))
    assert service.submit(sn, ok.id, expected_version=None).status == InvoiceStatus.UNDER_REVIEW

    _, _, over = _invoice(slug, Decimal("4325000.01"), ext_date=date(2026, 9, 1), proj=proj,
                          sn=sn, counterparty=_counterparty("100000000002"))
    with pytest.raises(DomainError) as exc:
        service.submit(sn, over.id, expected_version=None)
    assert exc.value.code == "E-INV-01"
    assert exc.value.message == ("Сумма счёта 4 325 000,01 тг превышает 1000 МРП "
                                 "(4 325 000,00 тг). Оплата без договора невозможна. "
                                 "Оформите договор.")


def test_last_year_invoice_uses_last_year_mrp(company_context):
    slug = company_context["slug"]
    sn, _, inv = _invoice(slug, Decimal("4000000.00"), ext_date=date(2025, 12, 20))
    # 1000 × 3 932 = 3 932 000,00 < 4 000 000,00.
    assert _code(lambda: service.submit(sn, inv.id, expected_version=None)) == "E-INV-01"


def test_currency_invoice_compares_in_kzt(company_context):
    slug = company_context["slug"]
    ExchangeRate.objects.update_or_create(currency_code="USD", on_date=date(2026, 9, 1),
                                          defaults={"rate": Decimal("500"), "source": "nbrk"})
    sn, _, inv = _invoice(slug, Decimal("9000.00"), ext_date=date(2026, 9, 1))
    inv, _ = service.update_draft(sn, inv.id, expected_version=None,
                                  data={"currency_code": "USD"})
    assert inv.amount_kzt == Decimal("4500000.00") and inv.rate_source == "nbrk"
    assert _code(lambda: service.submit(sn, inv.id, expected_version=None)) == "E-INV-01"


# ── по договору, AC-008 ────────────────────────────────────────────────

def _active_agreement(slug, amount):
    proj = _setup(slug)
    sn = s.actor(slug, s.SN, "bpp-sn")
    req = _approved_request(sn, proj, amount)
    agr = agreement_service.create_from_plan(sn, [str(i.id) for i in req.items.all()])
    agr, _ = agreement_service.update_draft(sn, agr.id, expected_version=None, data={
        "counterparty_id": str(_counterparty("100000000009").pk), "ext_number": "Д-1",
        "ext_date": timezone.localdate()})
    agreement_service.submit(sn, agr.id, expected_version=None)
    for user_id in (s.FD, GD):
        process = signoff.get_process_for("bpp.agreement", str(agr.pk))
        task = next(t for st in process["stages"] for t in st["tasks"]
                    if t["user_id"] == user_id and t["state"] == "pending")
        signoff.decide_many(actor_id=user_id, items=[{"task_id": task["id"],
                                                      "decision": "approve"}])
    agr.refresh_from_db()
    return sn, proj, agr


def test_ac008_invoice_over_agreement_remaining(company_context):
    slug = company_context["slug"]
    sn, _, agr = _active_agreement(slug, 10_000_000)
    first = service.create_from_agreement(sn, agr.id)
    item = first.lines.get()
    first, _ = service.update_draft(sn, first.id, expected_version=None, data={
        "ext_number": "1", "amount": 9_700_000,
        "lines": [{"id": str(item.pk), "qty": "0.5", "amount": 9_700_000}]})
    service.submit(sn, first.id, expected_version=None)

    second = service.create_from_agreement(sn, agr.id)
    line = second.lines.get()
    second, _ = service.update_draft(sn, second.id, expected_version=None, data={
        "ext_number": "2", "amount": 500_000,
        "lines": [{"id": str(line.pk), "qty": "0.5", "amount": 500_000}]})
    with pytest.raises(DomainError) as exc:
        service.submit(sn, second.id, expected_version=None)
    assert exc.value.code == "E-INV-02"
    assert exc.value.message == (f"Сумма счёта превышает остаток по договору {agr.number} на "
                                 f"200 000,00 KZT. Уменьшите сумму или оформите "
                                 f"дополнительное соглашение.")


def test_terminated_agreement_takes_no_new_invoices(company_context):
    slug = company_context["slug"]
    sn, _, agr = _active_agreement(slug, 1_000_000)
    assert "create_invoice" in agreement_service.allowed_actions(sn, agr)
    inv = service.create_from_agreement(sn, agr.id)
    inv, _ = service.update_draft(sn, inv.id, expected_version=None, data={"ext_number": "9"})
    agreement_service.terminate(_fd(slug), agr.id, expected_version=None,
                                comment="Поставщик сорвал сроки")
    agr.refresh_from_db()
    assert "create_invoice" not in agreement_service.allowed_actions(sn, agr)
    with pytest.raises(DomainError) as exc:
        service.submit(sn, inv.id, expected_version=None)
    assert exc.value.code == "BR-046" and "расторгнут" in exc.value.message


# ── дубль, решения ФД ──────────────────────────────────────────────────

def test_duplicate_is_e_inv_03_with_link(company_context):
    slug = company_context["slug"]
    sn, proj, first = _submitted(slug, 100)
    _, _, second = _invoice(slug, 50, proj=proj, sn=sn,
                            counterparty=Counterparty.objects.get(pk=first.counterparty_id))
    with pytest.raises(DomainError) as exc:
        service.submit(sn, second.id, expected_version=None)
    assert exc.value.code == "E-INV-03"
    assert exc.value.message == (f"Счёт № 145 от {first.ext_date:%d.%m.%Y} ТОО «Альфа» уже "
                                 f"зарегистрирован как {first.number}. Откройте существующий "
                                 f"счёт.")
    assert exc.value.fields[0]["existing_id"] == str(first.pk)


def test_ac013_double_pay_with_same_key_is_one_decision(company_context):
    slug = company_context["slug"]
    _, _, inv = _submitted(slug, 100)
    s.grant(slug, s.FD, "bpp-fd")
    headers = {**s.auth(slug, s.FD), "HTTP_IDEMPOTENCY_KEY": "pay-1"}
    client = Client()
    first = client.post(f"{BASE}/invoices/{inv.pk}/decision", data={"decision": "pay"}, **headers)
    again = client.post(f"{BASE}/invoices/{inv.pk}/decision", data={"decision": "pay"}, **headers)
    assert first.status_code == 200, first.content
    assert again.status_code == 200 and again.json()["status"] == "to_pay"
    with use_company(slug):   # клиент после ответа возвращает search_path на public
        assert AuditLog.objects.filter(object_id=str(inv.pk), action="fd_pay").count() == 1


def test_not_payable_needs_comment_and_releases_budget(company_context):
    slug = company_context["slug"]
    _, proj, inv = _submitted(slug, 100)
    assert calc.committed_for(proj.id, s.metal().id) == Decimal("100.00")
    assert _code(lambda: decisions.decide(_fd(slug), inv.id, decision="not_payable",
                                          comment="нет")) == "BR-060"
    inv = decisions.decide(_fd(slug), inv.id, decision="not_payable",
                           comment="Цена выше рыночной")
    assert inv.status == InvoiceStatus.NOT_PAYABLE
    # Позиция заявки держит свой план; строка счёта больше не считается.
    assert calc.committed_for(proj.id, s.metal().id) == Decimal("100.00")
    assert read.card(_fd(slug), inv)["lines"][0]["amount_available"] == Decimal("100.00")


def test_batch_pay_reports_each_invoice(company_context):
    slug = company_context["slug"]
    sn, proj, good = _submitted(slug, 100, limit=1_000)
    _, _, bad = _submitted(slug, 200, proj=proj, sn=sn,
                           counterparty=_counterparty("100000000003"))
    # Лимит урезан в обход сервиса — бюджет превышен «на текущий момент».
    BudgetLine.objects.filter(article_id=s.metal().id).update(limit_amount=Decimal("250"))

    result = decisions.decide_batch(_fd(slug), [str(good.pk), str(bad.pk)], decision="pay")

    assert result["ok"] == [] and len(result["failed"]) == 2
    assert "превышен" in result["failed"][0]["reason"]


def test_inbox_approve_is_guarded_by_budget(company_context):
    slug = company_context["slug"]
    _, _, inv = _submitted(slug, 100, limit=1_000)
    BudgetLine.objects.filter(article_id=s.metal().id).update(limit_amount=Decimal("50"))
    process = signoff.get_process_for("bpp.invoice", str(inv.pk))
    task = process["stages"][0]["tasks"][0]

    result = signoff.decide_many(actor_id=s.FD, items=[{"task_id": task["id"],
                                                        "decision": "approve"}])[0]

    assert not result["ok"] and "превышен" in result["error"]
    inv.refresh_from_db()
    assert inv.status == InvoiceStatus.UNDER_REVIEW


# ── оплата и закрывающие документы (D-13) ──────────────────────────────

def _to_pay(slug, *amounts, **kwargs):
    sn, proj, inv = _submitted(slug, *amounts, **kwargs)
    return sn, proj, decisions.decide(_fd(slug), inv.id, decision="pay")


def test_partial_then_full_payment_and_overpay_is_br052(company_context):
    slug = company_context["slug"]
    _, _, inv = _to_pay(slug, 1000)
    buh = _buh(slug)
    today = timezone.localdate()
    inv = payments.mark_paid(buh, inv.id, pay_date=today, amount=400, pp_number="11")
    assert inv.status == InvoiceStatus.PARTIALLY_PAID
    assert _code(lambda: payments.mark_paid(buh, inv.id, pay_date=today, amount=700)) == "BR-052"
    inv = payments.mark_paid(buh, inv.id, pay_date=today, amount=600)
    assert inv.status == InvoiceStatus.PAID
    assert Counterparty.objects.get(pk=inv.counterparty_id).successful_documents == 1


def test_unmark_only_while_bank_has_not_confirmed(company_context):
    slug = company_context["slug"]
    _, _, inv = _to_pay(slug, 1000)
    buh = _buh(slug)
    inv = payments.mark_paid(buh, inv.id, pay_date=timezone.localdate(), amount=1000)
    mark = inv.payments.get()
    inv = payments.unmark(buh, inv.id, mark.pk, comment="Ошибка в сумме платежа")
    assert inv.status == InvoiceStatus.TO_PAY

    inv = payments.mark_paid(buh, inv.id, pay_date=timezone.localdate(), amount=1000)
    Invoice.objects.filter(pk=inv.pk).update(paid_bank_amount=Decimal("1000"))
    mark = inv.payments.filter(cancelled_at__isnull=True).get()
    with pytest.raises(DomainError) as exc:
        payments.unmark(buh, inv.id, mark.pk, comment="Ошибка в сумме платежа")
    assert exc.value.status == 409


def test_closing_docs_after_payment_only(company_context):
    slug = company_context["slug"]
    sn, _, inv = _to_pay(slug, 1000)
    buh = _buh(slug)
    assert _code(lambda: payments.request_docs(buh, inv.id)) == "E-STS-01"
    payments.mark_paid(buh, inv.id, pay_date=timezone.localdate(), amount=1000)

    inv = payments.request_docs(buh, inv.id)
    assert inv.status == InvoiceStatus.AWAITING_DOCS
    assert inv.docs_required == {"avr": False, "waybill": True, "vat_invoice": False}
    pending = closing_docs_pending_for_user(s.SN)
    assert [row["number"] for row in pending] == [inv.number]
    assert closing_docs_pending_for_user(s.SN2) == []

    inv = payments.submit_docs(sn, inv.id)
    assert inv.status == InvoiceStatus.DOCS_PROVIDED
    inv = payments.return_docs(buh, inv.id, comment="Накладная без подписи")
    assert inv.status == InvoiceStatus.AWAITING_DOCS
    payments.submit_docs(sn, inv.id)
    inv = payments.accept_docs(buh, inv.id)
    assert inv.status == InvoiceStatus.CLOSED


def test_cancel_by_author_before_decision_and_by_fd_before_payment(company_context):
    slug = company_context["slug"]
    sn, proj, inv = _submitted(slug, 100)
    inv = service.cancel(sn, inv.id, expected_version=None, comment="Поставщик отказался")
    assert inv.status == InvoiceStatus.CANCELLED
    assert signoff.get_process_for("bpp.invoice", str(inv.pk))["state"] != "pending"

    _, _, other = _to_pay(slug, 50, proj=proj, sn=sn, counterparty=_counterparty("100000000004"))
    assert _code(lambda: service.cancel(sn, other.id, expected_version=None,
                                        comment="Поставщик отказался")) == "E-ACC-01"
    other = service.cancel(_fd(slug), other.id, expected_version=None,
                           comment="Счёт выставлен ошибочно")
    assert other.status == InvoiceStatus.CANCELLED


# ── бюджет, дробление, поиск ───────────────────────────────────────────

def test_line_over_plan_uses_article_balance_br043(company_context):
    slug = company_context["slug"]
    sn, proj, inv = _invoice(slug, 1000, limit=1_100)            # свободно 100
    line = inv.lines.get()
    inv, _ = service.update_draft(sn, inv.id, expected_version=None, data={
        "amount": 1200, "lines": [{"id": str(line.pk), "qty": 1, "amount": 1200}]})
    with pytest.raises(DomainError) as exc:
        service.submit(sn, inv.id, expected_version=None)
    assert exc.value.code == "BR-043"
    assert "на 200,00 KZT" in exc.value.message and "100,00 KZT недостаточно" in exc.value.message

    inv, _ = service.update_draft(sn, inv.id, expected_version=None, data={
        "amount": 1080, "lines": [{"id": str(line.pk), "qty": 1, "amount": 1080}]})
    service.submit(sn, inv.id, expected_version=None)
    assert calc.committed_for(proj.id, s.metal().id) == Decimal("1080.00")
    assert calc.committed_for(proj.id, s.metal().id) == calc.committed_reference(
        proj.id, s.metal().id)


def test_possible_split_flag_d17(company_context):
    slug = company_context["slug"]
    cp = _counterparty()
    sn, proj, first = _submitted(slug, Decimal("2000000"), counterparty=cp,
                                 ext_date=timezone.localdate() - timedelta(days=5))
    _, _, second = _invoice(slug, Decimal("2000000"), proj=proj, sn=sn, counterparty=cp)
    second, _ = service.update_draft(sn, second.id, expected_version=None,
                                     data={"ext_number": "146"})
    service.submit(sn, second.id, expected_version=None)
    _, _, third = _invoice(slug, Decimal("1000000"), proj=proj, sn=sn, counterparty=cp)
    third, _ = service.update_draft(sn, third.id, expected_version=None,
                                    data={"ext_number": "147"})
    third = service.submit(sn, third.id, expected_version=None)

    flags = read.split_flags([first, second, third])
    assert str(third.pk) in flags                  # 5 000 000 за 30 дней > 4 325 000
    assert str(first.pk) not in flags


def test_find_by_number_for_reconciliation(company_context):
    slug = company_context["slug"]
    _, _, inv = _submitted(slug, 100)
    found = find_by_number(inv.number.lower())
    assert found["id"] == str(inv.pk) and found["counterparty_reg_number"] == "100000000001"
    assert find_by_number("СЧ-2000-000001") is None


def test_draft_with_bank_match_is_not_deleted(company_context):
    """Сверка выписки (A4.2, D-S4-3) сопоставляет платёж и с черновиком — «на
    проверку». Пока сопоставление не отменено, черновик не удаляется (409
    ``E-STATE-01``, а не 500 от PROTECT); отменённое уходит вместе со счётом."""
    from apps.bpp.models import PaymentMatch
    from apps.bpp.services.bank import matching
    from apps.bpp.tests.bank import common as bank

    slug = company_context["slug"]
    sn, _, inv = _invoice(slug, 100)
    imp = bank.loaded_import(bank.org_account(), [
        {"amount": "100", "purpose": f"Оплата по счёту {inv.number}",
         "recipient_bin": "100000000001"}])
    matching.auto_match(imp.pk)
    match = PaymentMatch.objects.get(invoice=inv)
    assert (match.state, match.review_reason) == ("review", "invoice_status")

    with pytest.raises(DomainError) as exc:
        service.delete_draft(sn, inv.id, expected_version=None)
    assert (exc.value.code, exc.value.status) == ("E-STATE-01", 409)
    assert inv.number in exc.value.message

    PaymentMatch.objects.filter(pk=match.pk).update(state="cancelled")
    service.delete_draft(sn, inv.id, expected_version=None)
    assert not Invoice.objects.filter(pk=inv.pk).exists()
    assert not PaymentMatch.objects.filter(pk=match.pk).exists()


def test_http_create_patch_and_registry_tabs(company_context):
    slug = company_context["slug"]
    proj = _setup(slug)
    sn = s.actor(slug, s.SN, "bpp-sn")
    req = _approved_request(sn, proj, 100)
    cp = _counterparty()     # до первого запроса: клиент возвращает search_path на public
    client = Client()
    created = client.post(f"{BASE}/invoices", data={
        "item_ids": [str(i.id) for i in req.items.all()]}, **s.auth(slug, s.SN))
    assert created.status_code == 201, created.content
    card = created.json()
    assert card["number"].startswith("СЧ-") and card["basis"] == "no_contract"
    assert card["threshold"] == "4325000.00" and card["initiator_role"] == "sn"
    # Черновик удаляют, а не отменяют.
    assert "delete" in card["allowed_actions"] and "cancel" not in card["allowed_actions"]

    patched = client.patch(f"{BASE}/invoices/{card['id']}", data={
        "version": card["version"], "counterparty_id": str(cp.pk), "ext_number": "7"},
        **s.auth(slug, s.SN))
    assert patched.status_code == 200, patched.content
    submitted = client.post(f"{BASE}/invoices/{card['id']}/submit",
                            data={"version": patched.json()["version"]}, **s.auth(slug, s.SN))
    assert submitted.status_code == 200, submitted.content
    assert "cancel" in submitted.json()["allowed_actions"]

    s.grant(slug, s.FD, "bpp-fd")
    tab = client.get(f"{BASE}/invoices?tab=fd", **s.auth(slug, s.FD)).json()
    assert [row["number"] for row in tab["items"]] == [card["number"]]
    assert client.get(f"{BASE}/invoices?tab=to_pay", **s.auth(slug, s.FD)).json()["total"] == 0


def test_fd_cannot_cancel_invoice_while_bank_holds_payment(company_context):
    """Выписка пришла раньше отметки БУХ: автосверка поставила действующее
    сопоставление на счёт «К оплате» (D-S4-3). Отмена такого счёта
    освободила бы статью бюджета, а «Оплачено факт» платёж продолжал бы
    считать, — поэтому 409 ``E-STATE-01``, как у отмены отметки оплаты, и
    «Отменить» нет в действиях. Отменили сопоставление — счёт отменяется."""
    from apps.bpp.models import PaymentMatch
    from apps.bpp.services.bank import matching
    from apps.bpp.tests.bank import common as bank

    slug = company_context["slug"]
    _, _, inv = _to_pay(slug, 1000)
    imp = bank.loaded_import(bank.org_account(), [
        {"amount": "1000", "purpose": f"Оплата по счёту {inv.number}",
         "recipient_bin": "100000000001"}])
    matching.auto_match(imp.pk)
    assert PaymentMatch.objects.get(invoice=inv).state == "active"
    inv.refresh_from_db()
    assert inv.paid_bank_amount == Decimal("1000")
    assert not inv.payments.exists()                 # отметки БУХ ещё нет

    fd = _fd(slug)
    assert "cancel" not in service.allowed_actions(fd, inv)
    with pytest.raises(DomainError) as exc:
        service.cancel(fd, inv.id, expected_version=None, comment="Счёт выставлен ошибочно")
    assert (exc.value.code, exc.value.status) == ("E-STATE-01", 409)
    assert inv.number in exc.value.message and "сопоставление" in exc.value.message
    inv.refresh_from_db()
    assert inv.status == InvoiceStatus.TO_PAY

    line = imp.lines.get()
    matching.cancel_match(s.FD, line.pk, "Платёж не по этому счёту")
    inv.refresh_from_db()
    assert inv.paid_bank_amount == 0
    assert "cancel" in service.allowed_actions(fd, inv)
    inv = service.cancel(fd, inv.id, expected_version=None, comment="Счёт выставлен ошибочно")
    assert inv.status == InvoiceStatus.CANCELLED
