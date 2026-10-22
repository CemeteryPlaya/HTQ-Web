"""БЗО одной компании ведётся в другой (решение 19.10).

Hi-Tech Group LTD (здесь — D) ведёт БЗО в головном офисе Hi-Tech Qazaqstan
(H): «Проекты», бюджеты, заявки, договоры и счета живут в схеме H, ПМ входит
только в D и видит там данные H — только свои проекты. Члены D «просто есть»
в H — участники без входа.
"""

import pytest
from django.core.cache import cache
from django.test import Client

from apps.access.tests.helpers import assign, auth, patch_json, superuser_token, token
from apps.companies import interface as companies
from apps.companies.models import Company, CompanyMembership, CompanyModule, CompanyStatus
from apps.companies.services import lifecycle
from htqweb.tenancy import bpp_delegation
from htqweb.tenancy.db import use_company

PM, OTHER = 41, 42


@pytest.fixture
def pair(two_company_schemas):
    """D ведёт БЗО в H. Возвращает (D, H)."""
    delegator, host = two_company_schemas
    Company.objects.filter(slug=delegator).update(
        bpp_data_company=Company.objects.get(slug=host))
    cache.clear()
    return delegator, host


def _headers(company, user_id=PM):
    return {**auth(token(user_id=user_id, sub=str(user_id), company=company)),
            "HTTP_X_HTQ_COMPANY": company}


def _project(company, code, manager):
    from apps.project.services import projects

    with use_company(company):
        return projects.create(code=code, name=f"Проект {code}", country_code="KZ",
                               actor_id=1, manager_user_id=manager)


# ── Какие запросы — БЗО ──────────────────────────────────────────────────

class _Req:
    def __init__(self, path, method="GET", **query):
        self.path, self.method, self.GET = path, method, query


@pytest.mark.parametrize("path,method,query,expected", [
    ("/api/bpp/v1/requests", "GET", {}, True),
    ("/api/bpp/v1/invoices/1/submit", "POST", {}, True),
    ("/api/project/v1/projects", "GET", {}, True),
    ("/api/files/v1/bpp.purchase_request/x/files/", "POST", {}, True),
    ("/api/signoff/v1/processes", "GET", {"subject_type": "bpp.invoice"}, True),
    ("/api/signoff/v1/processes", "GET", {"subject_type": "hr.bonus"}, False),
    ("/api/signoff/v1/processes", "GET", {}, False),
    ("/api/bpp/v1/holding/summary", "GET", {}, False),
    ("/api/files/v1/types", "GET", {}, False),
    ("/api/hr/v1/employees/", "GET", {}, False),
    ("/api/tasks/v1/projects/", "GET", {}, False),
])
def test_what_counts_as_a_bpp_request(path, method, query, expected):
    assert bpp_delegation.is_bpp_request(_Req(path, method, **query)) is expected


# ── Маршрутизация ────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_pm_on_own_subdomain_sees_only_own_projects_of_the_host(pair):
    delegator, host = pair
    own = _project(host, "П-001", PM)
    _project(host, "П-002", OTHER)
    _project(delegator, "П-900", PM)  # в схеме D — её из вида должно не быть
    assign(host, PM, "project.projects", "read")

    resp = Client().get("/api/project/v1/projects", **_headers(delegator))
    assert resp.status_code == 200, resp.content
    assert [p["id"] for p in resp.json()] == [str(own.id)]


@pytest.mark.django_db
def test_other_domains_stay_in_own_company(pair):
    from apps.hr.models import Department

    delegator, host = pair
    with use_company(delegator):
        Department.objects.create(name="Отдел D", path="d")
    with use_company(host):
        Department.objects.create(name="Отдел H", path="h")

    resp = Client().get("/api/hr/v1/departments/", **_headers(delegator))
    assert resp.status_code == 200, resp.content
    assert [d["name"] for d in resp.json()] == ["Отдел D"]


@pytest.mark.django_db
def test_roles_of_own_company_do_not_open_host_data(pair):
    """Права на данные БЗО — в компании данных: роль в D их не открывает."""
    delegator, host = pair
    _project(host, "П-001", PM)
    assign(delegator, PM, "project.projects", "read")

    resp = Client().get("/api/project/v1/projects", **_headers(delegator))
    assert resp.status_code == 403


@pytest.mark.django_db
def test_node_rights_inside_bpp_services_come_from_the_host(pair):
    """Узлы БЗО внутри сервисов (``bpp/services/core/permissions.py``) —
    права компании данных. Иначе ПМ на своём поддомене проходил гейт модуля,
    но терял блоки «Обзора», роль инициатора заявки и бюджеты (стенд 19.10)."""
    delegator, host = pair
    assign(host, PM, "bpp", "read")

    resp = Client().get("/api/bpp/v1/overview", **_headers(delegator))
    assert resp.status_code == 200, resp.content
    assert {"requests", "budgets"} <= set(resp.json())


@pytest.mark.django_db
def test_project_rights_of_the_host_allow_editing_from_own_subdomain(pair):
    from apps.project.models import Project

    delegator, host = pair
    own = _project(host, "П-001", PM)
    assign(host, PM, "project.projects", "full")

    resp = patch_json(Client(), f"/api/project/v1/projects/{own.id}",
                      {"name": "Новое имя"}, **_headers(delegator))
    assert resp.status_code == 200, resp.content
    with use_company(host):
        assert Project.objects.get(pk=own.pk).name == "Новое имя"


@pytest.mark.django_db
def test_all_projects_node_of_the_host_shows_every_project(pair):
    delegator, host = pair
    _project(host, "П-001", PM)
    _project(host, "П-002", OTHER)
    assign(host, PM, "project.projects", "read")
    assign(host, PM, "project.all", "view")

    resp = Client().get("/api/project/v1/projects", **_headers(delegator))
    assert sorted(p["code"] for p in resp.json()) == ["П-001", "П-002"]


@pytest.mark.django_db
def test_token_of_the_data_company_is_refused_on_the_delegator_host(pair):
    """Claim токена сверяется с компанией АДРЕСА, хотя запрос работает в
    данных компании данных: токен головного офиса на поддомене LTD — 403."""
    delegator, host = pair
    assign(host, PM, "project.projects", "read")
    headers = {**auth(token(user_id=PM, sub=str(PM), company=host)),
               "HTTP_X_HTQ_COMPANY": delegator}

    assert Client().get("/api/project/v1/projects", **headers).status_code == 403


@pytest.mark.django_db
@pytest.mark.parametrize("off_at", ["delegator", "host"])
def test_bpp_module_switch_is_checked_at_both_companies(pair, off_at):
    """«Проекты» — обязательное ядро без рубильника компании, а БЗО — нет."""
    delegator, host = pair
    company = Company.objects.get(slug=delegator if off_at == "delegator" else host)
    CompanyModule.objects.create(company=company, app_label="bpp", enabled=False)
    cache.clear()
    assign(host, PM, "bpp", "read")

    resp = Client().get("/api/bpp/v1/overview", **_headers(delegator))
    assert resp.status_code == 503
    assert resp.json()["service"] == "bpp"


@pytest.mark.django_db
def test_archived_host_is_not_reachable_through_delegator(pair):
    delegator, host = pair
    Company.objects.filter(slug=host).update(status=CompanyStatus.ARCHIVED)
    cache.clear()
    assign(host, PM, "project.projects", "read")

    resp = Client().get("/api/project/v1/projects", **_headers(delegator))
    assert resp.status_code == 404


# ── Права в /me ──────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_me_shows_bpp_rights_from_the_host(pair):
    delegator, host = pair
    assign(host, PM, "project.projects", "read")
    assign(delegator, PM, "hr", "read")

    body = Client().get("/api/access/v1/me", **_headers(delegator)).json()
    assert body["permissions"]["project"]["level"] == "read"
    assert body["permissions"]["hr"]["level"] == "read"
    assert "view" in body["depth"]["project.projects"]


@pytest.mark.django_db
def test_me_keeps_task_board_node_of_own_company(pair):
    """Доски задач не делегируются: «Доска задач проекта» — по ролям своей
    компании, как её проверяет ``tasks/services/board_scope.py``."""
    delegator, host = pair
    # Право на весь модуль в H: без явной строки доска унаследовала бы его
    # на фронте от предка ``project``, пришедшего из H.
    assign(host, PM, "project", "read")
    assign(host, PM, "project.board", "view")

    body = Client().get("/api/access/v1/me", **_headers(delegator)).json()
    assert "view" in body["depth"]["project"]
    assert body["depth"]["project.board"] == []

    assign(delegator, PM, "project.board", "view")
    body = Client().get("/api/access/v1/me", **_headers(delegator)).json()
    assert body["depth"]["project.board"] == ["view"]


# ── Участник без входа ───────────────────────────────────────────────────

@pytest.mark.django_db
def test_member_without_login_cannot_enter(pair):
    delegator, host = pair
    companies.grant_membership(delegator, PM)
    companies.grant_membership(host, PM, login_allowed=False)

    assert companies.user_may_enter_company(PM, delegator)
    assert not companies.user_may_enter_company(PM, host)
    assert host in companies.user_company_slugs(PM)  # числится в компании
    assert companies.default_company_slug(PM) == delegator

    mine = Client().get("/api/companies/v1/me", **_headers(delegator)).json()
    assert [row["slug"] for row in mine] == [delegator]
    assert mine[0]["bpp_data_company_slug"] == host


@pytest.mark.django_db
def test_superuser_toggles_login(pair):
    delegator, host = pair
    companies.grant_membership(host, PM)
    admin = {**auth(superuser_token(company=host)), "HTTP_X_HTQ_COMPANY": host}

    resp = patch_json(Client(), f"/api/companies/v1/companies/{host}/memberships/{PM}",
                      {"login_allowed": False}, **admin)
    assert resp.status_code == 200, resp.content
    assert resp.json()["login_allowed"] is False
    assert not companies.user_may_enter_company(PM, host)

    plain = _headers(host, user_id=OTHER)
    refused = patch_json(Client(), f"/api/companies/v1/companies/{host}/memberships/{PM}",
                         {"login_allowed": True}, **plain)
    assert refused.status_code == 403


@pytest.mark.django_db
def test_linking_card_in_host_gives_membership_without_login(pair):
    from apps.hr.services import employee_service

    delegator, host = pair
    companies.grant_membership(delegator, PM)
    with use_company(host):
        employee_service.ensure_company_membership(PM)
        employee_service.ensure_company_membership(OTHER)

    assert not CompanyMembership.objects.get(company__slug=host, user_id=PM).login_allowed
    assert CompanyMembership.objects.get(company__slug=host, user_id=OTHER).login_allowed


# ── Где вести БЗО: проверки ──────────────────────────────────────────────

@pytest.mark.django_db
def test_setting_and_clearing_the_data_company(two_company_schemas):
    delegator, host = two_company_schemas
    company = lifecycle.update_company(delegator, bpp_data_company=host)
    assert company.bpp_data_company_slug == host
    company = lifecycle.update_company(delegator, bpp_data_company=None)
    assert company.bpp_data_company_slug is None


@pytest.mark.django_db
def test_data_company_validation(two_company_schemas):
    delegator, host = two_company_schemas
    cases = [
        lambda: lifecycle.update_company(delegator, bpp_data_company=delegator),
        lambda: lifecycle.update_company(delegator, bpp_data_company="no-such"),
    ]
    for case in cases:
        with pytest.raises(lifecycle.LifecycleError):
            case()

    # Цепочка: H сама ведёт БЗО в D — тогда D не может вести своё в H.
    lifecycle.update_company(host, bpp_data_company=delegator)
    with pytest.raises(lifecycle.LifecycleError):
        lifecycle.update_company(delegator, bpp_data_company=host)


@pytest.mark.django_db
def test_data_company_must_be_active_and_have_the_module(two_company_schemas):
    delegator, host = two_company_schemas
    Company.objects.filter(slug=host).update(status=CompanyStatus.ARCHIVED)
    cache.clear()
    with pytest.raises(lifecycle.BppDataCompanyInvalid):
        lifecycle.update_company(delegator, bpp_data_company=host)

    Company.objects.filter(slug=host).update(status=CompanyStatus.ACTIVE)
    CompanyModule.objects.create(company=Company.objects.get(slug=host),
                                 app_label="bpp", enabled=False)
    cache.clear()
    with pytest.raises(lifecycle.BppDataCompanyInvalid):
        lifecycle.update_company(delegator, bpp_data_company=host)


@pytest.mark.django_db
def test_company_with_own_projects_cannot_move_its_bpp(two_company_schemas):
    delegator, host = two_company_schemas
    _project(delegator, "П-777", PM)
    with pytest.raises(lifecycle.BppDataCompanyInvalid):
        lifecycle.update_company(delegator, bpp_data_company=host)


# ── Уведомления ──────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_bell_shows_host_events_to_member_without_login(pair):
    from apps.notifications.models import Notification
    from apps.notifications.services import center

    delegator, host = pair
    companies.grant_membership(delegator, PM)
    companies.grant_membership(host, PM, login_allowed=False)
    Notification.objects.create(recipient_id=PM, company_slug=host,
                                event="bpp.request_returned", title="Заявка вернулась")

    titles = [row["title"] for row in center.latest(PM, company_slug=delegator)]
    assert titles == ["Заявка вернулась"]

    # С входом в H — у человека свой колокольчик там, здесь не задваиваем.
    CompanyMembership.objects.filter(company__slug=host, user_id=PM).update(login_allowed=True)
    cache.clear()
    assert center.latest(PM, company_slug=delegator) == []


@pytest.mark.django_db
def test_digest_links_member_without_login_to_own_subdomain(pair):
    from apps.notifications.services import digest

    delegator, host = pair
    companies.grant_membership(delegator, PM)
    companies.grant_membership(host, PM, login_allowed=False)

    assert digest._link_company(PM, host) == delegator
    assert digest._link_company(PM, delegator) == delegator
