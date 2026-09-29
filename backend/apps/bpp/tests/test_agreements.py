"""Договор (ТЗ §09, §15.3, задача B3.1): из плана закупок, проверки при
отправке (BR-030…034, D-14, D-19, D-20), маршрут ФД → ТД → ОД → ГД, поиск для
счёта (AC-007), расторжение, допсоглашение (D-18), «Задействовано» (D-09)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from django.test import Client
from django.utils import timezone

from apps.bpp.models import AgreementStatus, AuditLog, Counterparty, CounterpartyStatus
from apps.bpp.services.agreements import agreements as service
from apps.bpp.services.agreements import read
from apps.bpp.services.budget import balance
from apps.bpp.services.budget import committed as calc
from apps.bpp.services.plan import service as plan
from apps.bpp.services.requests import requests as request_service
from apps.bpp.tests import stage2 as s
from apps.signoff import interface as signoff
from htqweb.errors import DomainError

pytestmark = pytest.mark.django_db
GD = 910
BASE = "/api/bpp/v1"


def _counterparty(reg: str = "100000000001", **over) -> Counterparty:
    fields = {"name": "ТОО «Альфа»", "kind": "legal", "country_code": "KZ", "reg_number": reg,
              "is_vat_payer": True, "verified_override": True, **over}
    return Counterparty.objects.create(**fields)


def _routes():
    for user_id in (s.FD, s.TD, s.OD, GD):
        s.user(user_id)
    stages = [{"order": n, "name": name, "quorum": "any", "approver_kind": "users",
               "user_ids": [uid]}
              for n, (name, uid) in enumerate((("ФД", s.FD), ("ТД", s.TD), ("ОД", s.OD),
                                               ("ГД", GD)), start=1)]
    signoff.configure_route(subject_type="bpp.agreement", name="Договор", stages=stages,
                            flags={"reject_comment_min": 10})
    signoff.configure_route(
        subject_type="bpp.agreement", scope="supplementary", name="Допсоглашение",
        stages=[{"order": 1, "name": "ФД", "quorum": "any", "approver_kind": "users",
                 "user_ids": [s.FD],
                 "condition": [{"field": "amount_delta", "op": "gt", "value": 0}]}],
        flags={"skip_unmatched_groups": True})


def _approved_request(slug, sn, proj, *amounts):
    req = request_service.create_draft(sn, {**s.header(proj, s.metal()),
                                            "items": s.items(*[(1, a) for a in amounts])})
    req = request_service.submit(sn, req.id, expected_version=None)
    s.decide(req, s.TD, "approve"), s.decide(req, s.OD, "approve")
    return req


def _setup(slug, limit=10_000):
    s.user(s.SN)
    proj = s.project(members=[s.SN])
    s.approved_budget(slug, proj, {s.metal(): limit})
    s.request_route()
    _routes()
    return proj


def _draft(slug, *amounts, counterparty=None, limit=10_000):
    proj = _setup(slug, limit)
    sn = s.actor(slug, s.SN, "bpp-sn")
    req = _approved_request(slug, sn, proj, *amounts)
    agr = service.create_from_plan(sn, [str(i.id) for i in req.items.all()])
    cp = counterparty or _counterparty()
    agr, _ = service.update_draft(sn, agr.id, expected_version=None, data={
        "counterparty_id": str(cp.pk), "ext_number": "145", "ext_date": timezone.localdate()})
    return sn, proj, req, agr


def _decide(agr, user_id, decision="approve", comment=""):
    process = signoff.get_process_for("bpp.agreement", str(agr.pk))
    task = next(t for stage in process["stages"] for t in stage["tasks"]
                if t["user_id"] == user_id and t["state"] == "pending")
    return signoff.decide_many(actor_id=user_id, items=[
        {"task_id": task["id"], "decision": decision, "comment": comment}])[0]


def _code(call) -> str:
    with pytest.raises(DomainError) as exc:
        call()
    return exc.value.code


# ── из плана ───────────────────────────────────────────────────────────

def test_draft_from_plan_takes_project_article_and_remaining(company_context):
    slug = company_context["slug"]
    sn, proj, req, agr = _draft(slug, 100, 50)

    assert agr.number.startswith("ДГ-")
    assert (str(agr.project_id), str(agr.article_id)) == (str(proj.id), str(s.metal().id))
    assert agr.amount == Decimal("150.00") and agr.agreement_type == "goods"
    assert agr.status == AgreementStatus.DRAFT
    # Позиции в черновике договора держат остаток плана (CALC-005).
    rows = plan.plan_items(sn)["items"]
    assert {row["qty_left"] for row in rows} == {Decimal("0")}
    assert {row["qty_in_agreements"] for row in rows} == {Decimal("1.000")}
    assert not any(row["selectable"] for row in rows)


def test_vat_defaults_from_refdata_on_the_agreement_date(company_context):
    slug = company_context["slug"]
    sn, _, _, agr = _draft(slug, 1160)
    assert agr.vat_source == "refdata" and agr.vat_rate == Decimal("16.00")
    assert agr.vat_amount == Decimal("160.00")

    agr, _ = service.update_draft(sn, agr.id, expected_version=None,
                                  data={"ext_date": date(2025, 6, 1)})
    assert agr.vat_rate == Decimal("12.00")      # ставка страны на дату договора

    agr, _ = service.update_draft(sn, agr.id, expected_version=None, data={"vat_rate": 10})
    assert agr.vat_source == "manual" and agr.vat_rate == Decimal("10")
    last = AuditLog.objects.filter(object_id=str(agr.pk), action="updated").order_by("-created_at").first()
    assert last.changes["after"]["vat_source"] == "manual"   # правка в журнале (D-14)


# ── проверки отправки ──────────────────────────────────────────────────

def test_blocked_counterparty_is_e_ctr_01(company_context):
    slug = company_context["slug"]
    blocked = _counterparty("100000000002", status=CounterpartyStatus.BLOCKED,
                            block_reason="нет оригиналов", blocked_at=timezone.now())
    sn, _, _, agr = _draft(slug, 100)
    assert _code(lambda: service.update_draft(
        sn, agr.id, expected_version=None,
        data={"counterparty_id": str(blocked.pk)})) == "E-CTR-01"
    Counterparty.objects.filter(pk=agr.counterparty_id).update(
        status=CounterpartyStatus.BLOCKED, blocked_at=timezone.now(), block_reason="спор")
    assert _code(lambda: service.submit(sn, agr.id, expected_version=None)) == "E-CTR-01"


def test_unverified_counterparty_needs_confirmation(company_context):
    slug = company_context["slug"]
    sn, _, _, agr = _draft(slug, 100, counterparty=_counterparty(verified_override=False))
    assert _code(lambda: service.submit(sn, agr.id, expected_version=None)) == "E-CTR-05"

    agr = service.submit(sn, agr.id, expected_version=None, counterparty_confirmed=True)

    assert agr.status == AgreementStatus.ON_REVIEW
    entry = AuditLog.objects.get(object_id=str(agr.pk), action="submitted")
    assert entry.changes["counterparty_confirmed"] == "ТОО «Альфа»"
    assert not Counterparty.objects.get(pk=agr.counterparty_id).verified_override  # метку не ставит


def test_closed_agreement_items_must_sum_to_amount(company_context):
    slug = company_context["slug"]
    sn, _, _, agr = _draft(slug, 100)
    agr, _ = service.update_draft(sn, agr.id, expected_version=None, data={"amount": 120})
    assert _code(lambda: service.submit(sn, agr.id, expected_version=None)) == "BR-033"


def test_over_plan_beyond_article_balance_is_br_034(company_context):
    slug = company_context["slug"]
    sn, proj, req, agr = _draft(slug, 1000, limit=1500)   # план 1000, свободно 500
    item = agr.items.get()
    agr, _ = service.update_draft(sn, agr.id, expected_version=None, data={
        "amount": 1600, "items": [{"id": str(item.pk), "qty": 1, "amount": 1600}]})
    assert _code(lambda: service.submit(sn, agr.id, expected_version=None)) == "BR-034"

    agr, _ = service.update_draft(sn, agr.id, expected_version=None, data={
        "amount": 1400, "items": [{"id": str(item.pk), "qty": 1, "amount": 1400}]})
    service.submit(sn, agr.id, expected_version=None)
    # Задействовано = max(план 1000; договор 1400) — сверхплановое заняло остаток.
    assert calc.committed_for(proj.id, s.metal().id) == Decimal("1400.00")
    assert calc.committed_for(proj.id, s.metal().id) == calc.committed_reference(
        proj.id, s.metal().id)


def test_duplicate_number_and_date_is_br_032(company_context):
    slug = company_context["slug"]
    sn, proj, _, first = _draft(slug, 100)
    service.submit(sn, first.id, expected_version=None)
    req = _approved_request(slug, sn, proj, 50)
    second = service.create_from_plan(sn, [str(i.id) for i in req.items.all()])
    second, _ = service.update_draft(sn, second.id, expected_version=None, data={
        "counterparty_id": str(first.counterparty_id), "ext_number": "145",
        "ext_date": first.ext_date})
    with pytest.raises(DomainError) as exc:
        service.submit(sn, second.id, expected_version=None)
    assert exc.value.code == "BR-032"
    assert exc.value.fields[0]["existing_id"] == str(first.pk)


def test_required_fields_and_at_least_one_item(company_context):
    slug = company_context["slug"]
    sn, _, _, agr = _draft(slug, 100)
    agr, _ = service.update_draft(sn, agr.id, expected_version=None, data={"ext_number": ""})
    with pytest.raises(DomainError) as exc:
        service.submit(sn, agr.id, expected_version=None)
    assert exc.value.code == "E-AGR-01"
    assert "„Номер договора“" in exc.value.message


# ── маршрут и поиск для счёта ──────────────────────────────────────────

def test_search_finds_only_after_gd_ac007(company_context):
    slug = company_context["slug"]
    sn, proj, _, agr = _draft(slug, 100)
    service.submit(sn, agr.id, expected_version=None)
    find = lambda: read.search_for_invoice(sn, project_id=proj.id, article_id=s.metal().id)  # noqa: E731
    for user_id in (s.FD, s.TD, s.OD):
        _decide(agr, user_id)
        assert find() == []                         # без ГД договор не виден в поиске
    _decide(agr, GD)

    agr.refresh_from_db()
    assert agr.status == AgreementStatus.ACTIVE
    assert [row["number"] for row in find()] == [agr.number]
    assert Counterparty.objects.get(pk=agr.counterparty_id).successful_documents == 1


def test_rework_keeps_positions_and_rejection_releases_them(company_context):
    slug = company_context["slug"]
    sn, _, _, agr = _draft(slug, 100)
    service.submit(sn, agr.id, expected_version=None)
    _decide(agr, s.FD, "rework", "Уточните номер договора")
    agr.refresh_from_db()
    assert agr.status == AgreementStatus.REWORK
    assert agr.rework_comment == "Уточните номер договора"

    service.submit(sn, agr.id, expected_version=None)
    _decide(agr, s.FD, "reject", "Контрагент не подходит")
    agr.refresh_from_db()
    assert agr.status == AgreementStatus.REJECTED
    assert plan.plan_items(sn)["items"][0]["qty_left"] == Decimal("1.000")


# ── расторжение, допсоглашение, D-09 ───────────────────────────────────

def _active(slug, *amounts, limit=10_000):
    sn, proj, req, agr = _draft(slug, *amounts, limit=limit)
    service.submit(sn, agr.id, expected_version=None)
    for user_id in (s.FD, s.TD, s.OD, GD):
        _decide(agr, user_id)
    agr.refresh_from_db()
    return sn, proj, agr


def test_terminate_releases_the_unused_reserve(company_context):
    slug = company_context["slug"]
    sn, proj, agr = _active(slug, 300)
    fd = s.actor(slug, s.FD, "bpp-fd")
    assert calc.committed_for(proj.id, s.metal().id) == Decimal("300.00")
    assert _code(lambda: service.terminate(fd, agr.id, expected_version=None,
                                           comment="коротко")) == "BR-060"

    service.terminate(fd, agr.id, expected_version=None, comment="Поставщик сорвал сроки")

    agr.refresh_from_db()
    assert agr.status == AgreementStatus.TERMINATED
    # Позиция вернулась в план — её резерв снова считается по плану заявки.
    assert plan.plan_items(sn)["items"][0]["qty_left"] == Decimal("1.000")
    assert _code(lambda: service.terminate(sn, agr.id, expected_version=None,
                                           comment="Поставщик сорвал сроки")) == "E-ACC-01"


def test_supplement_without_amount_change_takes_effect_at_once(company_context):
    slug = company_context["slug"]
    sn, _, agr = _active(slug, 300)
    supplement = service.create_supplement(sn, agr.id)
    supplement, _ = service.update_draft(sn, supplement.id, expected_version=None, data={
        "ext_number": "145-1", "valid_to": date(2099, 12, 31)})

    supplement = service.submit(sn, supplement.id, expected_version=None)

    assert supplement.status == AgreementStatus.ACTIVE      # этапов нет — сразу в силе
    agr.refresh_from_db()
    assert agr.valid_to == date(2099, 12, 31)               # срок продлён у родителя


def test_supplement_with_growth_goes_to_fd_and_checks_balance(company_context):
    slug = company_context["slug"]
    sn, proj, agr = _active(slug, 300, limit=500)            # свободно 200
    supplement = service.create_supplement(sn, agr.id)
    supplement, _ = service.update_draft(sn, supplement.id, expected_version=None, data={
        "ext_number": "145-2", "amount": 250})
    assert _code(lambda: service.submit(sn, supplement.id, expected_version=None)) == "BR-034"

    supplement, _ = service.update_draft(sn, supplement.id, expected_version=None,
                                         data={"amount": 150})
    supplement = service.submit(sn, supplement.id, expected_version=None)
    assert supplement.status == AgreementStatus.ON_REVIEW
    _decide(supplement, s.FD)

    assert service.effective_amount(agr) == Decimal("450.00")       # суммы складываются
    assert calc.committed_for(proj.id, s.metal().id) == Decimal("450.00")
    assert calc.committed_for(proj.id, s.metal().id) == calc.committed_reference(
        proj.id, s.metal().id)


def test_open_agreement_does_not_commit_budget_d09(company_context):
    slug = company_context["slug"]
    sn, proj, _, agr = _draft(slug, 300)
    agr, _ = service.update_draft(sn, agr.id, expected_version=None, data={"is_open": True})
    assert agr.amount is None and not agr.items.filter(amount__isnull=False).exists()
    service.submit(sn, agr.id, expected_version=None)
    # Позиция заявки держит свой план; открытый договор сверху ничего не занимает.
    assert calc.committed_for(proj.id, s.metal().id) == Decimal("300.00")
    assert balance.balance(proj.id, s.metal().id)["available"] == Decimal("9700.00")


def test_withdraw_before_decisions_returns_to_draft(company_context):
    slug = company_context["slug"]
    sn, _, _, agr = _draft(slug, 100)
    service.submit(sn, agr.id, expected_version=None)
    agr = service.withdraw(sn, agr.id, expected_version=None)
    assert agr.status == AgreementStatus.DRAFT


# ── ручки ──────────────────────────────────────────────────────────────

def test_http_create_from_plan_patch_and_card(company_context):
    slug = company_context["slug"]
    proj = _setup(slug)
    sn = s.actor(slug, s.SN, "bpp-sn")
    req = _approved_request(slug, sn, proj, 100)
    # До первого запроса: клиент после ответа возвращает search_path на public.
    cp = _counterparty()
    client = Client()
    created = client.post(f"{BASE}/agreements", data={
        "item_ids": [str(i.id) for i in req.items.all()]}, **s.auth(slug, s.SN))
    assert created.status_code == 201, created.content
    card = created.json()
    assert card["number"].startswith("ДГ-") and card["allowed_actions"][:2] == ["save", "submit"]

    patched = client.patch(f"{BASE}/agreements/{card['id']}", data={
        "version": card["version"], "counterparty_id": str(cp.pk), "ext_number": "7"},
        **s.auth(slug, s.SN))
    assert patched.status_code == 200, patched.content
    body = patched.json()
    assert body["counterparty"]["name"] == "ТОО «Альфа»"
    assert body["vat_rate"] == "16.00" and body["vat_source"] == "refdata"

    listing = client.get(f"{BASE}/agreements", **s.auth(slug, s.SN)).json()
    assert [row["number"] for row in listing["items"]] == [card["number"]]
    other = client.get(f"{BASE}/agreements/{card['id']}", **s.auth(slug, s.SN2))
    assert other.status_code in (403, 404)
