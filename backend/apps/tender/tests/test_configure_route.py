"""Маршрут выбора поставщиков командой ``tender_configure_route`` (T5.2)."""

from __future__ import annotations

from io import StringIO

import pytest
from django.core.management import CommandError, call_command

from apps.hr.models import Department, Position
from apps.signoff.models import ApprovalRoute

pytestmark = pytest.mark.django_db


def _run(slug, *args) -> str:
    out = StringIO()
    call_command("tender_configure_route", "--company", slug, *args, stdout=out)
    return out.getvalue()


def _fd() -> int:
    dept = Department.objects.create(name="Дирекция", path="dir-tender")
    return Position.objects.create(title="Финансовый директор", department=dept, weight=600).pk


def test_route_quality_then_fd_and_idempotent(company_context):
    slug = company_context["slug"]
    fd = _fd()
    assert "заведён маршрут" in _run(slug)
    route = ApprovalRoute.objects.get(subject_type="tender.award", is_active=True)
    first, second = route.stages.order_by("order")
    assert (first.name, first.approver_kind, first.approver_key) == (
        "Проверка качества", "subject", "quality_reviewer")
    assert [row.position_id for row in second.roles.all()] == [fd]
    assert route.forbid_self_approval and route.reject_comment_min == 10
    assert "уже есть" in _run(slug)
    assert ApprovalRoute.objects.filter(subject_type="tender.award").count() == 1


def test_dry_run_writes_nothing(company_context):
    slug = company_context["slug"]
    _fd()
    assert "завести маршрут" in _run(slug, "--dry-run")
    assert not ApprovalRoute.objects.filter(subject_type="tender.award").exists()


def test_without_fd_position_is_explained(company_context):
    with pytest.raises(CommandError, match="Финансовый директор"):
        _run(company_context["slug"])
