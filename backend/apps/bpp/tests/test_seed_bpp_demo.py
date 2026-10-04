"""Демо-данные модуля (B4.2): документы во всех статусах, повторный запуск
ничего не делает, ``--purge`` удаляет только своё."""

from __future__ import annotations

import io

import pytest
from django.core.management import CommandError, call_command

from apps.bpp.models import (
    AccountableFundsRequest,
    AdvanceReport,
    Agreement,
    Budget,
    Counterparty,
    Invoice,
    PurchaseRequest,
)
from apps.bpp.tests import stage2 as s
from apps.bpp.tests.test_files import memory_storage  # noqa: F401  (фикстура)
from apps.files.models import FileObject
from apps.project import interface as projects
from apps.signoff import interface as signoff

pytestmark = pytest.mark.django_db
GD, BUH = 910, 907


def _routes():
    for uid in (s.FD, s.TD, s.OD, GD, BUH, s.SN, s.PM):
        s.user(uid)
    s.request_route()

    def one(order, name, uid, **extra):
        return {"order": order, "name": name, "quorum": "any", "approver_kind": "users",
                "user_ids": [uid], **extra}
    signoff.configure_route(subject_type="bpp.agreement", name="Договор",
                            stages=[one(1, "ФД", s.FD), one(2, "ГД", GD)])
    signoff.configure_route(subject_type="bpp.agreement", scope="supplementary",
                            name="Допсоглашение", stages=[one(1, "ФД", s.FD)])
    signoff.configure_route(subject_type="bpp.invoice", name="Счёт",
                            stages=[one(1, "ФД", s.FD, requirement_key="bpp:budget")])
    signoff.configure_route(subject_type="bpp.accountable_funds_request", name="Подотчёт",
                            stages=[one(1, "ФД", s.FD)])
    signoff.configure_route(subject_type="bpp.advance_report", name="Авансовый отчёт",
                            stages=[one(1, "ФД", s.FD)])


def _setup(slug):
    _routes()
    s.grant(slug, s.SN, "bpp-sn"), s.grant(slug, s.PM, "bpp-pm")
    s.grant(slug, s.FD, "bpp-fd"), s.grant(slug, BUH, "bpp-buh")
    s.metal(), s.article("T-CABLE", "Кабельная продукция", "supply"), s.design(), s.pcs()


def _run(slug, **options) -> str:
    out = io.StringIO()
    call_command("seed_bpp_demo", company=slug, stdout=out, **options)
    return out.getvalue()


def test_seed_walks_every_status_and_purge_removes_only_its_own(company_context):
    slug = company_context["slug"]
    _setup(slug)
    foreign = s.project("П-777", members=[s.SN])     # чужой проект — purge его не трогает
    people = {"sn": s.SN, "pm": s.PM, "fd": s.FD, "buh": BUH}

    text = _run(slug, **people)
    assert "Готово." in text
    ids = projects.project_ids_by_code(["ДЕМО-01", "ДЕМО-02"])
    assert set(ids) == {"ДЕМО-01", "ДЕМО-02"}
    assert Budget.objects.filter(project_id__in=ids.values(), status="approved").count() == 2
    statuses = set(PurchaseRequest.objects.filter(project_id__in=ids.values())
                   .values_list("status", flat=True))
    assert {"draft", "in_approval", "rework", "rejected", "approved"} <= statuses
    assert set(Agreement.objects.values_list("status", flat=True)) == {"active", "draft"}
    supplement = Agreement.objects.get(parent_agreement__isnull=False)
    assert (supplement.status, supplement.amount) == ("active", 300000)
    assert set(Invoice.objects.values_list("status", flat=True)) == {
        "partially_paid", "draft", "under_review", "awaiting_docs", "returned", "not_payable",
        "docs_provided", "closed"}
    acc = AccountableFundsRequest.objects.get()
    assert acc.status == "awaiting_report"
    assert sorted(acc.reports.values_list("approval_state", flat=True)) == ["approved", "draft"]
    # Договор, допсоглашение и счета отправлены с файлами (ТЗ §21 — обязательны
    # для отправки), закрывающие — с накладной, авансовые отчёты — с чеком.
    live = FileObject.objects.filter(
        owner_type__in=["bpp.agreement", "bpp.invoice", "bpp.advance_report"],
        deleted_at__isnull=True)
    assert set(live.values_list("file_type_id", flat=True)) == {
        "agreement", "invoice", "waybill", "advance_report"}

    # Повторный запуск ничего не пишет.
    assert "уже есть" in _run(slug, **people)
    assert PurchaseRequest.objects.filter(project_id__in=ids.values()).count() == 8

    pending_invoice = Invoice.objects.get(status="under_review")
    text = _run(slug, purge=True)
    assert "проекты — 2" in text
    assert not projects.project_ids_by_code(["ДЕМО-01", "ДЕМО-02"])
    assert not (Invoice.objects.exists() or Agreement.objects.exists()
                or PurchaseRequest.objects.exists() or AccountableFundsRequest.objects.exists()
                or AdvanceReport.objects.exists())
    assert signoff.get_process_for("bpp.invoice", str(pending_invoice.pk)) is None
    assert not live.exists()                    # файлы демо-документов убраны вместе с ними
    assert not Counterparty.objects.filter(reg_number__startswith="99").exists()
    assert projects.project_ids_by_code(["П-777"]) == {"П-777": str(foreign.id)}


def test_missing_roles_and_routes_are_explained(company_context):
    slug = company_context["slug"]
    with pytest.raises(CommandError) as exc:
        _run(slug)
    assert "Нет держателя роли" in str(exc.value) and "--sn" in str(exc.value)

    for uid in (s.SN, s.PM, s.FD, BUH):
        s.user(uid)
    with pytest.raises(CommandError) as exc:
        _run(slug, sn=s.SN, pm=s.PM, fd=s.FD, buh=BUH)
    assert "bpp_configure_routes" in str(exc.value)
    assert not projects.project_ids_by_code(["ДЕМО-01"])
