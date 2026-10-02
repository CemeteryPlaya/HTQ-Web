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


def test_fd_and_gd_choose_the_option_of_an_agreement(company_context):
    """Альтернативу договора выбирают ФД и ГД, решает ГД (D-25, B5.1): признак
    «Выбирает вариант» — только у их этапов и только в маршруте договора."""
    _positions()
    _run(company_context["slug"])
    voting = {(route.subject_type, route.scope, stage.name)
              for route in ApprovalRoute.objects.filter(is_active=True)
              for stage in route.stages.all() if stage.votes_option}
    assert voting == {("bpp.agreement", "", "Финансовый директор"),
                      ("bpp.agreement", "", "Генеральный директор")}


def test_fd_and_adm_edit_the_routes_of_the_module(company_context, client):
    """В-09 (access/0018): маршруты документов модуля правят ФД и АДМ — и
    только их; СН — нет, чужие маршруты — только администратор платформы."""
    from apps.bpp.tests import stage2 as s

    slug = company_context["slug"]
    _positions()
    _run(slug)
    s.grant(slug, 31, "bpp-fd"), s.grant(slug, 32, "bpp-adm"), s.grant(slug, 33, "bpp-sn")
    foreign = ApprovalRoute.objects.create(subject_type="contracts.agreement", name="Старый")
    agreement = ApprovalRoute.objects.get(subject_type="bpp.agreement", scope="")
    gd_stage = agreement.stages.get(name="Генеральный директор")
    base = "/api/signoff/v1"

    for editor in (31, 32):
        listed = client.get(f"{base}/routes", **s.auth(slug, editor))
        assert listed.status_code == 200
        assert {row["subject_type"] for row in listed.json()} == {
            "bpp.purchase_request", "bpp.agreement", "bpp.invoice",
            "bpp.accountable_funds_request", "bpp.advance_report"}
        changed = client.patch(f"{base}/stages/{gd_stage.pk}", {"votes_option": False},
                               **s.auth(slug, editor))
        assert changed.status_code == 200, changed.content
        assert client.patch(f"{base}/routes/{foreign.pk}", {"name": "x"},
                            **s.auth(slug, editor)).status_code == 403

    assert client.get(f"{base}/routes", **s.auth(slug, 33)).status_code == 403
    assert client.patch(f"{base}/routes/{agreement.pk}", {"name": "x"},
                        **s.auth(slug, 33)).status_code == 403


def test_dry_run_writes_nothing(company_context):
    _positions()
    assert "завести маршрут" in _run(company_context["slug"], "--dry-run")
    assert not ApprovalRoute.objects.filter(subject_type="bpp.purchase_request").exists()
