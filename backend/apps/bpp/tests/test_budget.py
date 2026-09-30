"""Бюджет проекта (ТЗ §06, §15.1, задача B2.1): BR-001…004, версии, видимость."""

from __future__ import annotations

import json
from decimal import Decimal

import pytest
from django.test import Client

from apps.bpp.models import AuditLog, Budget, BudgetStatus, VersionState
from apps.bpp.services.budget import balance, budgets, read
from apps.bpp.services.requests import requests as request_service
from apps.bpp.tests import stage2 as s
from htqweb.errors import DomainError
from htqweb.tenancy.db import use_company

pytestmark = pytest.mark.django_db
BASE = "/api/bpp/v1"


def _fd(slug):
    return s.actor(slug, s.FD, "bpp-fd")


def _code(call) -> str:
    with pytest.raises(DomainError) as exc:
        call()
    return exc.value.code


def test_second_budget_of_a_project_is_br001_with_a_link(company_context):
    slug = company_context["slug"]
    proj, art = s.project(), s.metal()
    first = budgets.create(_fd(slug), project_id=proj.id,
                           lines=[{"article_id": art.id, "limit_amount": 100}])
    with pytest.raises(DomainError) as exc:
        budgets.create(_fd(slug), project_id=proj.id, lines=[])
    assert exc.value.code == "E-BUD-03"
    assert exc.value.message == (f"У проекта П-015 уже есть бюджет {first.number}. "
                                 f"Откройте его и выполните корректировку.")
    assert exc.value.fields[0]["existing_id"] == str(first.id)


def test_duplicate_article_names_the_first_line(company_context):
    slug = company_context["slug"]
    art = s.metal()
    with pytest.raises(DomainError) as exc:
        budgets.create(_fd(slug), project_id=s.project().id, lines=[
            {"article_id": art.id, "limit_amount": 1},
            {"article_id": s.design().id, "limit_amount": 1},
            {"article_id": art.id, "limit_amount": 2}])
    assert exc.value.code == "E-BUD-04"
    assert exc.value.message == "Статья „Металлопрокат“ уже есть в бюджете, строка 1."


def test_approve_needs_a_positive_total(company_context):
    slug = company_context["slug"]
    budget = budgets.create(_fd(slug), project_id=s.project().id,
                            lines=[{"article_id": s.metal().id, "limit_amount": 0}])
    assert _code(lambda: budgets.approve(_fd(slug), budget.id, expected_version=None)) \
        == "E-BUD-08"


def test_approve_makes_version_one_active(company_context):
    budget = s.approved_budget(company_context["slug"], s.project(), {s.metal(): 1000})
    assert budget.status == BudgetStatus.APPROVED
    assert budget.active_version.version_no == 1
    assert budget.active_version.state == VersionState.ACTIVE
    assert AuditLog.objects.filter(object_id=str(budget.id), action="approved").count() == 1


def _submitted_request(slug, proj, art, amount):
    s.request_route()
    sn = s.actor(slug, s.SN, "bpp-sn")
    req = request_service.create_draft(sn, {**s.header(proj, art),
                                            "items": s.items((1, amount))})
    return request_service.submit(sn, req.id, expected_version=None)


def test_correction_limit_below_committed_is_br004(company_context):
    slug = company_context["slug"]
    proj, art = s.project(), s.metal()
    budget = s.approved_budget(slug, proj, {art: 5_000_000})
    _submitted_request(slug, proj, art, 3_400_000)
    budgets.start_correction(_fd(slug), budget.id, expected_version=None)
    budgets.save_correction(_fd(slug), budget.id, expected_version=None,
                            lines=[{"article_id": art.id, "limit_amount": 3_000_000}])
    with pytest.raises(DomainError) as exc:
        budgets.approve_correction(_fd(slug), budget.id, expected_version=None,
                                   comment="Сокращаем лимит статьи")
    assert exc.value.code == "E-BUD-05"
    assert exc.value.message == ("Лимит статьи „Металлопрокат“ не может быть меньше "
                                 "задействованной суммы 3 400 000,00 KZT.")


def test_balance_follows_the_active_version_during_correction(company_context):
    slug = company_context["slug"]
    proj, art = s.project(), s.metal()
    budget = s.approved_budget(slug, proj, {art: 1000})
    budgets.start_correction(_fd(slug), budget.id, expected_version=None)
    budgets.save_correction(_fd(slug), budget.id, expected_version=None,
                            lines=[{"article_id": art.id, "limit_amount": 9000}])
    assert balance.balance(proj.id, art.id)["limit"] == Decimal("1000.00")

    budgets.approve_correction(_fd(slug), budget.id, expected_version=None,
                               comment="Увеличили по письму заказчика")
    assert balance.balance(proj.id, art.id)["limit"] == Decimal("9000.00")


def test_snapshot_of_the_old_version_survives_a_correction(company_context):
    slug = company_context["slug"]
    proj, art = s.project(), s.metal()
    budget = s.approved_budget(slug, proj, {art: 1000})
    budgets.start_correction(_fd(slug), budget.id, expected_version=None)
    budgets.save_correction(_fd(slug), budget.id, expected_version=None,
                            lines=[{"article_id": art.id, "limit_amount": 2000}])
    budgets.approve_correction(_fd(slug), budget.id, expected_version=None,
                               comment="Увеличили по письму заказчика")
    budget.refresh_from_db()
    old = read.version_snapshot(_fd(slug), budget, 1)
    assert old["state"] == VersionState.ARCHIVED
    assert old["lines"][0]["limit_amount"] == Decimal("1000.00")
    assert budget.active_version.version_no == 2


def test_cancel_correction_removes_only_the_draft(company_context):
    slug = company_context["slug"]
    budget = s.approved_budget(slug, s.project(), {s.metal(): 1000})
    budgets.start_correction(_fd(slug), budget.id, expected_version=None)
    budgets.cancel_correction(_fd(slug), budget.id, expected_version=None)
    budget.refresh_from_db()
    assert [v.version_no for v in budget.versions.all()] == [1]
    assert budget.active_version.version_no == 1


def test_line_with_committed_cannot_be_dropped_in_a_correction(company_context):
    """ТЗ §6.4: строку с «Задействовано» > 0 не удалить; пустую — можно."""
    slug = company_context["slug"]
    proj, metal, pipe = s.project(), s.metal(), s.article("T-PIPE", "Трубы", "supply")
    budget = s.approved_budget(slug, proj, {metal: 1000, pipe: 500})
    _submitted_request(slug, proj, metal, 100)
    budgets.start_correction(_fd(slug), budget.id, expected_version=None)
    assert _code(lambda: budgets.save_correction(
        _fd(slug), budget.id, expected_version=None,
        lines=[{"article_id": pipe.id, "limit_amount": 500}])) == "E-BUD-09"
    budgets.save_correction(_fd(slug), budget.id, expected_version=None,
                            lines=[{"article_id": metal.id, "limit_amount": 1000}])


def test_close_waits_for_requests_on_review_and_reopen_needs_a_comment(company_context):
    slug = company_context["slug"]
    proj, art = s.project(), s.metal()
    budget = s.approved_budget(slug, proj, {art: 1000})
    req = _submitted_request(slug, proj, art, 100)
    with pytest.raises(DomainError) as exc:
        budgets.close(_fd(slug), budget.id, expected_version=None)
    assert (exc.value.code, exc.value.status) == ("E-BUD-06", 409)
    assert exc.value.message.startswith("Бюджет нельзя закрыть: 1 заявок на согласовании.")

    request_service.withdraw(s.actor(slug, s.SN, "bpp-sn"), req.id, expected_version=None)
    budgets.close(_fd(slug), budget.id, expected_version=None)
    assert _code(lambda: budgets.reopen(_fd(slug), budget.id, expected_version=None,
                                        comment="коротко")) == "BR-060"
    reopened = budgets.reopen(_fd(slug), budget.id, expected_version=None,
                              comment="Проект продлён до весны")
    assert reopened.status == BudgetStatus.APPROVED


def test_stale_version_is_e_con_01(company_context):
    slug = company_context["slug"]
    budget = budgets.create(_fd(slug), project_id=s.project().id,
                            lines=[{"article_id": s.metal().id, "limit_amount": 5}])
    budgets.update_draft(_fd(slug), budget.id, expected_version=1, lines=[
        {"article_id": s.metal().id, "limit_amount": 6}])
    with pytest.raises(DomainError) as exc:
        budgets.update_draft(_fd(slug), budget.id, expected_version=1, lines=[])
    assert (exc.value.code, exc.value.status) == ("E-CON-01", 409)


def test_sn_sees_supply_lines_and_pm_only_member_projects(company_context):
    slug = company_context["slug"]
    mine, other = s.project("П-1", members=[s.PM]), s.project("П-2")
    budget = s.approved_budget(slug, mine, {s.metal(): 100, s.design(): 200})
    s.approved_budget(slug, other, {s.design(): 300})

    sn = s.actor(slug, s.SN, "bpp-sn")
    assert [row["article_name"] for row in read.card(sn, budget)["lines"]] == ["Металлопрокат"]

    pm = s.actor(slug, s.PM, "bpp-pm")
    assert [row["article_name"] for row in read.card(pm, budget)["lines"]] \
        == ["Проектные работы"]
    assert [item["project"]["code"] for item in read.registry(pm)["items"]] == ["П-1"]
    with pytest.raises(DomainError) as exc:
        budgets.get_visible(pm, Budget.objects.get(project_id=other.id).id)
    assert exc.value.status == 404


def test_http_create_is_idempotent_and_denied_to_sn(company_context):
    slug = company_context["slug"]
    proj, art = s.project(), s.metal()
    s.grant(slug, s.FD, "bpp-fd")
    s.grant(slug, s.SN, "bpp-sn")
    body = json.dumps({"project_id": str(proj.id),
                       "lines": [{"article_id": str(art.id), "limit_amount": "10.00"}]})
    client = Client()

    denied = client.post(f"{BASE}/budgets", body, **s.auth(slug, s.SN))
    assert denied.status_code == 403 and denied.json()["code"] == "E-ACC-01"

    headers = {**s.auth(slug, s.FD), "HTTP_IDEMPOTENCY_KEY": "k-1"}
    first = client.post(f"{BASE}/budgets", body, **headers)
    again = client.post(f"{BASE}/budgets", body, **headers)
    assert first.status_code == 201 and again.status_code == 201
    assert again["Idempotent-Replay"] == "true"
    with use_company(slug):  # запрос вернул search_path в public
        assert Budget.objects.count() == 1
    assert first.json()["number"] == "БДЖ-П-015"
    assert "approve" in first.json()["allowed_actions"]


# ── «Оплачено факт» (ТЗ §6.4, L-01, CALC-007, D-S4-7; остаток B этапа 4, B-2) ──

def _paid_by_bank(account, proj, art, amount, reg):
    """Счёт статьи ``art`` проекта ``proj``, оплаченный по выписке: автосверка
    поставила действующее сопоставление (D-S4-1)."""
    from apps.bpp.models import Invoice, PaymentMatch
    from apps.bpp.services.bank import matching
    from apps.bpp.tests.bank import common as bank

    inv = bank.orm_invoice(bank.counterparty(reg), amount)
    Invoice.objects.filter(pk=inv.pk).update(project_id=proj.id, article_id=art.id)
    imp = bank.loaded_import(account, [{"amount": str(amount), "recipient_bin": reg,
                                        "purpose": f"Оплата по счёту {inv.number}"}])
    matching.auto_match(imp.pk)
    assert PaymentMatch.objects.get(invoice=inv).state == "active"
    return inv


def test_paid_fact_follows_bank_matches_in_card_registry_and_export(company_context):
    from apps.bpp.tests.bank import common as bank

    slug = company_context["slug"]
    proj, metal, design = s.project(), s.metal(), s.design()
    budget = s.approved_budget(slug, proj, {metal: 5000, design: 2000})
    account = bank.org_account()
    _paid_by_bank(account, proj, metal, 1000, "100000000001")
    _paid_by_bank(account, proj, design, 300, "100000000002")
    _paid_by_bank(account, s.project("П-2"), metal, 700, "100000000003")  # чужой проект

    fd = _fd(slug)
    card = read.card(fd, budget)
    assert {row["article_name"]: row["paid_fact"] for row in card["lines"]} == {
        "Металлопрокат": Decimal("1000.00"), "Проектные работы": Decimal("300.00")}
    assert card["totals"]["paid_fact"] == Decimal("1300.00")
    assert {group["group_code"]: group["paid_fact"] for group in card["totals"]["by_group"]} \
        == {"supply": Decimal("1000.00"), "pm": Decimal("300.00")}
    # «Доступно» по-прежнему считается от «Задействовано», а не от оплат.
    assert card["totals"]["available"] == Decimal("7000.00")

    # СН видит «Оплачено факт» только своей группы статей (BR-010).
    sn_card = read.card(s.actor(slug, s.SN, "bpp-sn"), budget)
    assert [row["paid_fact"] for row in sn_card["lines"]] == [Decimal("1000.00")]
    assert sn_card["totals"]["paid_fact"] == Decimal("1000.00")

    [row] = read.registry(fd)["items"]
    assert row["paid_fact"] == Decimal("1300.00")
    [exported] = read.export_rows(user_id=s.FD, company=slug,
                                  filters={"status": None, "project_id": None})
    assert exported["paid_fact"] == Decimal("1300.00")

    # Блок корректировки показывает те же оплаты по статьям.
    budgets.start_correction(fd, budget.id, expected_version=None)
    budget.refresh_from_db()
    correction = read.card(fd, budget)["correction"]
    assert correction["totals"]["paid_fact"] == Decimal("1300.00")


def test_paid_fact_waits_for_approval_and_the_bank_submodule(company_context):
    from django.core.cache import cache

    from apps.companies.models import CompanyModule

    slug = company_context["slug"]
    fd = _fd(slug)
    draft = budgets.create(fd, project_id=s.project().id,
                           lines=[{"article_id": s.metal().id, "limit_amount": 100}])
    card = read.card(fd, draft)
    assert card["lines"][0]["paid_fact"] is None and card["totals"]["paid_fact"] is None
    assert card["totals"]["by_group"][0]["paid_fact"] is None
    assert read.registry(fd)["items"][0]["paid_fact"] is None

    # Выписка у компании выключена — «Оплачено факт» не показывается, как на
    # графике дашборда «Оплаты»; «Задействовано» — как было.
    approved = s.approved_budget(slug, s.project("П-2"), {s.metal(): 1000})
    CompanyModule.objects.create(company_id=company_context["id"], app_label="bpp_bank",
                                 enabled=False)
    cache.clear()          # рубильник кэшируется на 5 с
    card = read.card(fd, approved)
    assert card["lines"][0]["paid_fact"] is None and card["totals"]["paid_fact"] is None
    assert card["lines"][0]["committed"] == Decimal("0.00")
