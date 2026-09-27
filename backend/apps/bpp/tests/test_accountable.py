"""Подотчётные средства (задача B4.1): резерв в «Задействовано», выдача,
авансовые отчёты — поведение как в contracts, источник — статья проекта."""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.bpp.models import AccountableStatus
from apps.bpp.services.accountable import accountable as service
from apps.bpp.services.budget import balance
from apps.bpp.services.budget import committed as calc
from apps.bpp.tests import stage2 as s
from apps.bpp.tests.test_files import PDF, memory_storage  # noqa: F401  (фикстура)
from apps.signoff import interface as signoff
from htqweb.errors import DomainError

pytestmark = pytest.mark.django_db
BUH = 907


def _routes():
    for subject in ("bpp.accountable_funds_request", "bpp.advance_report"):
        s.user(s.FD)
        signoff.configure_route(subject_type=subject, name="ФД", stages=[
            {"order": 1, "name": "ФД", "quorum": "any", "approver_kind": "users",
             "user_ids": [s.FD]}])


def _approve(subject: str, object_id) -> None:
    process = signoff.get_process_for(subject, str(object_id))
    task = next(t for st in process["stages"] for t in st["tasks"] if t["state"] == "pending")
    assert signoff.decide_many(actor_id=task["user_id"], items=[
        {"task_id": task["id"], "decision": "approve"}])[0]["ok"]


def _setup(slug, limit=100_000):
    proj, art = s.project(), s.metal()
    s.approved_budget(slug, proj, {art: limit})
    _routes()
    return proj, art, s.actor(slug, s.SN, "bpp-sn")


def _pdf():
    return SimpleUploadedFile("chek.pdf", PDF, content_type="application/pdf")


def test_amount_over_the_balance_is_e_bud_01(company_context):
    slug = company_context["slug"]
    proj, art, sn = _setup(slug, limit=1000)
    with pytest.raises(DomainError) as exc:
        service.create(sn, project_id=proj.id, article_id=art.id, amount=1500, goal="Командировка")
    assert exc.value.code == "E-BUD-01"


def test_reserve_starts_on_submit_and_stays_after_closing(company_context):
    slug = company_context["slug"]
    proj, art, sn = _setup(slug)
    req = service.create(sn, project_id=proj.id, article_id=art.id, amount=600,
                         goal="Командировка на объект")
    assert calc.committed_for(proj.id, art.id) == Decimal("0.00")
    service.submit(sn, req.id, expected_version=None)
    assert calc.committed_for(proj.id, art.id) == Decimal("600.00")
    assert calc.committed_reference(proj.id, art.id) == Decimal("600.00")
    assert balance.balance(proj.id, art.id)["available"] == Decimal("99400.00")


def test_full_path_to_closed_by_reports(company_context):
    slug = company_context["slug"]
    proj, art, sn = _setup(slug)
    req = service.create(sn, project_id=proj.id, article_id=art.id, amount=1000,
                         goal="Расходные материалы")
    req = service.submit(sn, req.id, expected_version=None)
    assert req.status == AccountableStatus.ON_REVIEW
    _approve("bpp.accountable_funds_request", req.id)
    req.refresh_from_db()
    assert req.status == AccountableStatus.AWAITING_ACCOUNTING

    with pytest.raises(DomainError) as exc:
        service.mark_paid(sn, req.id, expected_version=None)
    assert exc.value.status == 403
    buh = s.actor(slug, BUH, "bpp-buh")
    req = service.mark_paid(buh, req.id, expected_version=None)
    assert req.status == AccountableStatus.AWAITING_REPORT

    first = service.add_report(sn, req.id, expense_name="Бензин", amount=400, upload=_pdf())
    service.submit_report(sn, first.id)
    with pytest.raises(DomainError) as exc:
        service.add_report(sn, req.id, expense_name="Лишнее", amount=700, upload=_pdf())
    assert exc.value.code == "E-ACN-01"

    _approve("bpp.advance_report", first.id)
    req.refresh_from_db()
    assert req.status == AccountableStatus.AWAITING_REPORT
    second = service.add_report(sn, req.id, expense_name="Крепёж", amount=600, upload=_pdf())
    service.submit_report(sn, second.id)
    _approve("bpp.advance_report", second.id)
    req.refresh_from_db()
    assert req.status == AccountableStatus.CLOSED
    assert service.reported_amount(req) == Decimal("1000.00")
    # Закрытый подотчёт остаётся в «Задействовано»: выданные деньги потрачены.
    assert calc.committed_for(proj.id, art.id) == Decimal("1000.00")


def test_only_the_owner_and_fd_see_the_request(company_context):
    slug = company_context["slug"]
    proj, art, sn = _setup(slug)
    req = service.create(sn, project_id=proj.id, article_id=art.id, amount=10, goal="Мелочи")
    with pytest.raises(DomainError):
        service.get_visible(s.actor(slug, s.SN2, "bpp-sn"), req.id)
    assert service.get_visible(s.actor(slug, s.FD, "bpp-fd"), req.id) == req
