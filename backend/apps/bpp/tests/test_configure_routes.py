"""Маршрут заявки БЗО командой ``bpp_configure_routes`` (план этапа 2, задача 1):
ТД → ОД по должностям, флаги БЗО, повторный запуск ничего не меняет."""

from __future__ import annotations

from io import StringIO

import pytest
from django.core.management import call_command

from apps.hr.models import Department, Position
from apps.signoff.models import ApprovalRoute

pytestmark = pytest.mark.django_db


def _positions():
    dept = Department.objects.create(name="Дирекция", path="dir-test")
    return {title: Position.objects.create(title=title, department=dept, weight=weight).pk
            for weight, title in enumerate(("Генеральный директор", "Финансовый директор",
                                            "Технический директор", "Операционный директор"),
                                           start=500)}


def _run(slug, *args) -> str:
    out = StringIO()
    call_command("bpp_configure_routes", "--company", slug, *args, stdout=out)
    return out.getvalue()


def test_route_td_then_od_with_bpp_flags_and_idempotent(company_context):
    slug = company_context["slug"]
    ids = _positions()
    assert "заведён маршрут" in _run(slug)

    route = ApprovalRoute.objects.get(subject_type="bpp.purchase_request", is_active=True)
    stages = list(route.stages.order_by("order"))
    assert [stage.name for stage in stages] == ["Технический директор", "Операционный директор"]
    assert [row.position_id for row in stages[0].roles.all()] == [ids["Технический директор"]]
    assert [row.position_id for row in stages[1].roles.all()] == [ids["Операционный директор"]]
    assert (route.forbid_self_approval, route.reject_comment_min, route.lazy_resolution) \
        == (True, 10, True)
    assert route.escalation_position_id == ids["Генеральный директор"]
    assert route.self_skip_notify_position_ids == [ids["Финансовый директор"]]

    assert "уже есть" in _run(slug)
    assert ApprovalRoute.objects.filter(subject_type="bpp.purchase_request").count() == 1


def test_every_document_of_the_module_gets_a_route(company_context):
    """С ФД и ГД заводятся маршруты всех документов модуля — подотчёт и
    авансовый отчёт тоже (одним этапом ФД): без маршрута их не отправить."""
    ids = _positions()
    _run(company_context["slug"])
    routes = {(r.subject_type, r.scope): r for r in ApprovalRoute.objects.filter(is_active=True)}
    assert set(routes) == {
        ("bpp.purchase_request", ""), ("bpp.agreement", ""), ("bpp.agreement", "supplementary"),
        ("bpp.invoice", ""), ("bpp.accountable_funds_request", ""), ("bpp.advance_report", "")}
    for key in (("bpp.accountable_funds_request", ""), ("bpp.advance_report", "")):
        stages = list(routes[key].stages.all())
        assert [row.position_id for row in stages[0].roles.all()] == [ids["Финансовый директор"]]
        assert len(stages) == 1 and routes[key].forbid_self_approval


def test_dry_run_writes_nothing(company_context):
    _positions()
    assert "завести маршрут" in _run(company_context["slug"], "--dry-run")
    assert not ApprovalRoute.objects.filter(subject_type="bpp.purchase_request").exists()
