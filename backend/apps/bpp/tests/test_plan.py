"""План закупок (ТЗ §08, BR-020, BR-021, задача B2.3)."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.bpp.models import AuditLog, PurchaseRequestItem
from apps.bpp.services.plan import service as plan
from apps.bpp.services.requests import requests as service
from apps.bpp.tests import stage2 as s
from htqweb.errors import DomainError

pytestmark = pytest.mark.django_db


def _approved(slug, sn, proj, art, *amounts, role="sn"):
    req = service.create_draft(sn, {**s.header(proj, art, role=role),
                                    "items": s.items(*[(1, a) for a in amounts])})
    req = service.submit(sn, req.id, expected_version=None)
    s.decide(req, s.TD, "approve"), s.decide(req, s.OD, "approve")
    return req


def _setup(slug):
    proj = s.project(members=[s.SN])
    s.approved_budget(slug, proj, {s.metal(): 10_000, s.design(): 10_000,
                                   s.article("T-PIPE", "Трубы", "supply"): 10_000})
    s.request_route()
    return proj


def test_positions_of_different_articles_are_br021(company_context):
    slug = company_context["slug"]
    proj = _setup(slug)
    sn = s.actor(slug, s.SN, "bpp-sn")
    first = _approved(slug, sn, proj, s.metal(), 100)
    second = _approved(slug, sn, proj, s.article("T-PIPE", "Трубы", "supply"), 200)
    ids = [str(first.items.get().id), str(second.items.get().id)]
    with pytest.raises(DomainError) as exc:
        plan.validate_selection(sn, ids, target="contract")
    assert exc.value.code == "E-PLN-01"
    assert exc.value.message == ("Для одного документа выберите позиции одного проекта и "
                                 "одной статьи")


def test_valid_selection_prepares_the_wizard(company_context):
    slug = company_context["slug"]
    proj = _setup(slug)
    sn = s.actor(slug, s.SN, "bpp-sn")
    req = _approved(slug, sn, proj, s.metal(), 100, 50)
    got = plan.validate_selection(sn, [str(i.id) for i in req.items.all()], target="invoice")
    assert got["ok"] and got["project_id"] == str(proj.id)
    assert got["article_id"] == str(s.metal().id) and got["purchase_type"] == "goods"
    assert [row["sys_number"] for row in got["items"]] == [f"{req.number}-01",
                                                           f"{req.number}-02"]


def test_fd_sees_every_position_read_only(company_context):
    slug = company_context["slug"]
    proj = _setup(slug)
    sn = s.actor(slug, s.SN, "bpp-sn")
    _approved(slug, sn, proj, s.metal(), 100)
    fd = s.actor(slug, s.FD, "bpp-fd")
    got = plan.plan_items(fd)
    assert got["read_only"] and got["total"] == 1
    assert got["items"][0]["selectable"] is False
    with pytest.raises(DomainError):
        plan.validate_selection(fd, [got["items"][0]["id"]], target="invoice")


def test_combined_sn_pm_sees_each_role_separately(company_context):
    slug = company_context["slug"]
    proj = _setup(slug)
    both = s.actor(slug, s.SN, "bpp-sn", "bpp-pm")
    _approved(slug, both, proj, s.metal(), 100, role="sn")
    _approved(slug, both, proj, s.design(), 200, role="pm")
    assert [r["article_name"] for r in plan.plan_items(both, role="sn")["items"]] \
        == ["Металлопрокат"]
    assert [r["article_name"] for r in plan.plan_items(both, role="pm")["items"]] \
        == ["Проектные работы"]


def test_overdue_positions_are_marked(company_context):
    slug = company_context["slug"]
    proj = _setup(slug)
    sn = s.actor(slug, s.SN, "bpp-sn")
    req = _approved(slug, sn, proj, s.metal(), 100)
    PurchaseRequestItem.objects.filter(request=req).update(
        need_date=timezone.localdate() - timedelta(days=1))
    assert plan.plan_items(sn)["items"][0]["overdue"] is True


def test_reassign_moves_positions_and_is_audited(company_context):
    slug = company_context["slug"]
    proj = _setup(slug)
    sn = s.actor(slug, s.SN, "bpp-sn")
    req = _approved(slug, sn, proj, s.metal(), 100)
    adm = s.actor(slug, 950, "bpp-adm")
    s.user(s.SN2)
    assert plan.reassign(adm, [str(req.items.get().id)], to_user_id=s.SN2) == 1
    assert plan.plan_items(sn)["items"] == []
    assert len(plan.plan_items(s.actor(slug, s.SN2, "bpp-sn"))["items"]) == 1
    assert AuditLog.objects.filter(object_id=str(req.id), action="item_reassigned").exists()
    with pytest.raises(DomainError) as exc:
        plan.reassign(sn, [str(req.items.get().id)], to_user_id=s.SN)
    assert exc.value.status == 403


def test_rejected_and_cancelled_requests_are_not_in_the_plan(company_context):
    slug = company_context["slug"]
    proj = _setup(slug)
    sn = s.actor(slug, s.SN, "bpp-sn")
    rejected = service.submit(sn, service.create_draft(sn, {
        **s.header(proj, s.metal()), "items": s.items((1, 100))}).id, expected_version=None)
    s.decide(rejected, s.TD, "reject", "Закупка не требуется в этом году")
    cancelled = _approved(slug, sn, proj, s.metal(), 200)
    service.cancel(s.actor(slug, s.FD, "bpp-fd"), cancelled.id, expected_version=None,
                   comment="Проект заморожен заказчиком")
    assert plan.plan_items(sn)["items"] == []
