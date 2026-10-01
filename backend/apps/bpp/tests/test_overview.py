"""«Обзор» модуля по ролям (ТЗ §05, §17; решение пользователя 01.10): ФД и
ГД — всё, БУХ — свои очереди, ПМ — только свои проекты и данные, СН, ТД, ОД,
АДМ — по ТЗ; несколько ролей — объединение; недоступный блок — без ключа."""

from __future__ import annotations

from decimal import Decimal as D

import pytest
from django.core.cache import cache
from django.utils import timezone

from apps.bpp.services import overview
from apps.bpp.services.invoices import invoices as invoice_service
from apps.bpp.services.plan import service as plan_service
from apps.bpp.services.requests import requests as request_service
from apps.bpp.tests import stage2 as s
from apps.bpp.tests import test_invoices as invoice_flow
from apps.bpp.tests.test_files import memory_storage  # noqa: F401  (фикстура)
from apps.companies.models import CompanyModule

pytestmark = pytest.mark.django_db
BASE = "/api/bpp/v1"
ADM, FD_ADM, SN_PM = 961, 962, 963
ALL_BLOCKS = {"budgets", "approvals", "requests", "plan", "agreements", "invoices",
              "accountable", "bank", "dashboard", "alternatives", "kpi", "admin"}


def _world(slug):
    """Свой проект (СН и ПМ — участники) и чужой (только СН); в обоих
    утверждённые бюджеты по «Снабжению» и «Проектному управлению». Заявки СН
    (утверждённая со счётом на решении ФД — в своём, черновик — в чужом) и
    черновик заявки ПМ в своём проекте."""
    for user_id in (s.SN, s.PM, s.FD):
        s.user(user_id)
    own = s.project("П-001", manager=s.PM, members=[s.SN, s.PM])
    other = s.project("П-002", members=[s.SN])
    s.approved_budget(slug, own, {s.metal(): 10_000_000, s.design(): 5_000_000})
    s.approved_budget(slug, other, {s.metal(): 7_000_000, s.design(): 3_000_000})
    s.request_route()
    invoice_flow._routes()
    sn, pm = s.actor(slug, s.SN, "bpp-sn"), s.actor(slug, s.PM, "bpp-pm")

    req = invoice_flow._approved_request(sn, own, 1_000_000)
    inv = invoice_service.create_from_plan(sn, [str(i.id) for i in req.items.all()])
    inv, _ = invoice_service.update_draft(sn, inv.id, expected_version=None, data={
        "counterparty_id": str(invoice_flow._counterparty().pk), "ext_number": "1",
        "ext_date": timezone.localdate()})
    invoice_flow._attach(inv)
    invoice_service.submit(sn, inv.id, expected_version=None)
    request_service.create_draft(sn, {**s.header(other, s.metal()),
                                      "items": s.items((1, 500_000))})
    request_service.create_draft(pm, {**s.header(own, s.design(), role="pm"),
                                      "items": s.items((1, 200_000))})


def _limits(view) -> dict[str, D]:
    """Лимит бюджета по коду проекта — каждый проект отдельно (решение 01.10)."""
    return {row["project"]["code"]: row["limit_amount"] for row in view["budgets"]["projects"]}


ALL = {"П-001": D("15000000.00"), "П-002": D("10000000.00")}


def test_fd_sees_every_block_and_all_the_money(company_context):
    slug = company_context["slug"]
    _world(slug)
    view = overview.overview(s.actor(slug, s.FD, "bpp-fd"))

    assert view["shows_money"] and set(view) - {"shows_money"} == ALL_BLOCKS
    assert _limits(view) == ALL                               # все строки всех бюджетов
    row = view["budgets"]["projects"][0]
    assert row["available"] == row["limit_amount"] - row["committed"] and row["budget_id"]
    assert view["invoices"]["tabs"]["fd"] == 1 and view["approvals"]["pending"] == 1
    assert view["requests"]["total"] == 3


def test_gd_sees_everything(company_context):
    """ГД видит всё (решение 01.10, access/0019): все деньги и документы,
    план закупок, подотчёт и выписки. Блока администрирования нет — он для
    тех, кто правит настройки или маршруты, а ГД их только смотрит."""
    slug = company_context["slug"]
    _world(slug)
    view = overview.overview(s.actor(slug, invoice_flow.GD, "bpp-gd"))

    assert _limits(view) == ALL and view["requests"]["total"] == 3
    # Выписки ГД видит — и очередь «банк не подтвердил»; решать и оплачивать
    # он не может, поэтому других очередей нет.
    assert view["invoices"]["total"] == 1
    assert view["invoices"]["tabs"] == {"bank_unconfirmed": 0}
    assert "submitted" in view["alternatives"] and "kpi" in view
    assert {"plan", "accountable", "bank", "dashboard"} <= set(view) and "admin" not in view
    assert view["plan"]["open"] > 0


def test_buh_sees_only_the_payment_queues(company_context):
    slug = company_context["slug"]
    _world(slug)
    view = overview.overview(s.actor(slug, invoice_flow.BUH, "bpp-buh"))

    assert not {"budgets", "requests", "plan", "alternatives", "kpi", "admin"} & set(view)
    assert set(view["invoices"]["tabs"]) == {"to_pay", "docs_provided", "bank_unconfirmed"}
    assert "awaiting_accounting" in view["accountable"]
    assert {"bank", "dashboard"} <= set(view)


def test_pm_sees_only_his_projects_and_his_documents(company_context):
    slug = company_context["slug"]
    _world(slug)
    view = overview.overview(s.actor(slug, s.PM, "bpp-pm"))

    assert _limits(view) == {"П-001": D("5000000.00")}   # своя группа статей своего проекта
    assert view["requests"]["total"] == 1 and view["invoices"]["total"] == 0
    assert not {"kpi", "dashboard", "bank", "admin"} & set(view)


def test_sn_sees_his_documents_alternatives_and_kpi(company_context):
    slug = company_context["slug"]
    _world(slug)
    view = overview.overview(s.actor(slug, s.SN, "bpp-sn"))

    assert _limits(view) == {"П-001": D("10000000.00"),  # «Снабжение» во всех проектах
                             "П-002": D("7000000.00")}
    assert view["requests"]["total"] == 2 and view["invoices"]["total"] == 1
    assert set(view["invoices"]["tabs"]) == {"awaiting_docs"}
    assert {"plan", "alternatives", "kpi"} <= set(view)
    assert "mine_submitted" in view["alternatives"]
    assert not {"dashboard", "bank", "admin"} & set(view)


def test_project_without_the_actors_lines_is_not_listed(company_context):
    """СН видит все проекты, но бюджет ПМ-статей ему не принадлежит —
    такого проекта в его списке нет (в реестре он с нулями)."""
    slug = company_context["slug"]
    _world(slug)
    pm_only = s.project("П-004", manager=s.PM, members=[s.PM])
    s.approved_budget(slug, pm_only, {s.design(): 1_000_000})

    assert "П-004" not in _limits(overview.overview(s.actor(slug, s.SN, "bpp-sn")))
    assert _limits(overview.overview(s.actor(slug, s.PM, "bpp-pm")))["П-004"] == D("1000000.00")


@pytest.mark.parametrize("user_id, role", [(s.TD, "bpp-td"), (s.OD, "bpp-od")])
def test_td_and_od_see_every_request_and_the_budgets(company_context, user_id, role):
    slug = company_context["slug"]
    _world(slug)
    view = overview.overview(s.actor(slug, user_id, role))

    assert view["requests"]["total"] == 3 and _limits(view) == ALL
    assert {"approvals", "agreements", "invoices", "dashboard"} <= set(view)
    assert view["invoices"]["tabs"] == {}       # чужих очередей нет
    assert not {"plan", "bank", "admin"} & set(view)
    assert ("kpi" in view) == (role == "bpp-od")     # отчёт R-01 — ФД, ГД, ОД


def test_adm_sees_counts_without_money_and_the_admin_block(company_context):
    slug = company_context["slug"]
    _world(slug)
    view = overview.overview(s.actor(slug, ADM, "bpp-adm"))

    assert view["shows_money"] is False and "projects" not in view["budgets"]
    assert view["requests"]["total"] == 3
    assert view["admin"] == {"no_executor": 0, "routes": True, "settings": True,
                             "refdata": True, "projects": True}
    assert not {"invoices", "dashboard", "bank", "plan", "kpi"} & set(view)


def test_two_roles_see_the_union(company_context):
    slug = company_context["slug"]
    _world(slug)
    view = overview.overview(s.actor(slug, FD_ADM, "bpp-fd", "bpp-adm"))

    assert set(view) - {"shows_money"} == ALL_BLOCKS and view["shows_money"]
    assert view["admin"]["settings"] is True


def test_plan_counts_every_initiator_role_of_the_user(company_context):
    """СН и ПМ в одном лице: реестр плана показывает одну роль за раз
    (переключателем), а «Обзор» — позиции обеих ролей."""
    slug = company_context["slug"]
    _world(slug)
    s.user(SN_PM)
    proj = s.project("П-003", manager=SN_PM, members=[SN_PM])
    s.approved_budget(slug, proj, {s.metal(): 4_000_000, s.design(): 4_000_000})
    both = s.actor(slug, SN_PM, "bpp-sn", "bpp-pm")
    for article, role in ((s.metal(), "sn"), (s.design(), "pm")):
        req = request_service.create_draft(both, {**s.header(proj, article, role=role),
                                                  "items": s.items((1, 100_000))})
        req = request_service.submit(both, req.id, expected_version=None)
        s.decide(req, s.TD, "approve"), s.decide(req, s.OD, "approve")

    assert overview.overview(both)["plan"]["open"] == 2
    assert plan_service.plan_items(both)["total"] == 1


def test_switched_off_submodule_removes_its_block(company_context):
    slug = company_context["slug"]
    _world(slug)
    CompanyModule.objects.create(company_id=company_context["id"],
                                 app_label="bpp_invoices", enabled=False)
    cache.clear()                        # рубильник кэшируется на 5 с

    view = overview.overview(s.actor(slug, s.FD, "bpp-fd"))
    assert "invoices" not in view and {"budgets", "requests", "agreements"} <= set(view)


def test_overview_numbers_match_the_registry_by_its_link(company_context, client):
    """Очередь ФД в «Обзоре» = ``total`` реестра счетов с ``tab=fd``."""
    slug = company_context["slug"]
    _world(slug)
    s.actor(slug, s.FD, "bpp-fd")

    view = client.get(f"{BASE}/overview", **s.auth(slug, s.FD))
    registry = client.get(f"{BASE}/invoices?tab=fd", **s.auth(slug, s.FD))

    assert view.status_code == 200, view.content
    assert view.json()["invoices"]["tabs"]["fd"] == registry.json()["total"] == 1
