"""Документы переноса (B6.1, задача 5): открытые — в модуль в своём статусе,
закрытые остаются в «Договорах»; «На согласовании» — черновиком с отзывом
старого процесса (D-B61-2); платёжные документы договора — счета (D-B61-6)."""

from __future__ import annotations

from datetime import datetime, timezone as dt_timezone
from decimal import Decimal

import pytest

from apps.bpp.models import (
    AccountableFundsRequest,
    Agreement,
    Invoice,
    MigrationLink,
    PurchaseRequest,
)
from apps.bpp.services.migration import links
from apps.bpp.tests import stage2 as s
from apps.bpp.tests.test_files import PDF, memory_storage  # noqa: F401  (фикстура)
from apps.contracts.models import (
    AccountableFundsRequest as OldAccountable,
    AdvanceReport as OldReport,
    AgreementItem as OldItem,
    CompletionAct,
    ContractPayment,
    GoodsInvoice,
)
from apps.contracts.models import Agreement as OldAgreement
from apps.contracts.tests.helpers import (
    make_administrator,
    make_advance_payment,
    make_agreement,
    make_budget,
    make_counterparty,
    make_country,
    make_invoice,
    make_line,
    make_program,
)
from apps.contracts.tests.test_approval_wiring import make_user
from apps.files import interface as files
from apps.media_files import interface as media
from apps.signoff import interface as signoff

from .common import ACTOR, migrate, write_maps

pytestmark = pytest.mark.django_db
PAID_AT = datetime(2026, 9, 1, 10, 0, tzinfo=dt_timezone.utc)


def _pay(model, agreement, amount, status, **over):
    return model.objects.create(administrator=agreement.budget_line.budget.administrator,
                                agreement=agreement, amount=Decimal(amount), status=status,
                                **over)


def _world():
    s.user(ACTOR), s.user(7)
    s.metal(), s.pcs()
    kz = make_country()
    admin = make_administrator(country=kz, project_name="Объект А")
    steel = make_program(name="Металл", code="3011")
    line = make_line(budget=make_budget(administrator=admin, approval_state="approved"),
                     program=steel, amount="5000000.00")
    supplier = make_counterparty(country=kz, bin_iin="123456789012")
    scan = media.store_file(data=PDF, filename="dogovor.pdf", mime="application/pdf",
                            scope="generic", owner_id=7, internal_authorized=True)["id"]

    signed = make_agreement(line=line, counterparty=supplier, number="Д-1",
                            amount="400000.00", status="signed", with_item=False,
                            file_id=str(scan), created_by=7)
    OldItem.objects.create(agreement=signed, line_no=1, name="Балка", unit="т",
                           quantity=Decimal("3"), amount=Decimal("300000.00"))
    OldItem.objects.create(agreement=signed, line_no=2, name="Лист", unit="шт",
                           quantity=Decimal("10"), amount=Decimal("100000.00"))
    _pay(ContractPayment, signed, "90000.00", "closed", paid_at=PAID_AT, paid_by=7,
         posting_number="ПР-77")

    running = make_agreement(line=line, counterparty=supplier, number="Д-2",
                             amount="120000.00", status="draft", created_by=7)
    approver = make_user("migration-approver")
    signoff.configure_route(subject_type=OldAgreement.SIGNOFF_SUBJECT_TYPE, name="Договор",
                            stages=[{"order": 1, "name": "ФД", "quorum": "any",
                                     "approver_kind": "users", "user_ids": [approver.id]}])
    signoff.start_process(subject_type=OldAgreement.SIGNOFF_SUBJECT_TYPE,
                          subject_id=running.id, initiator_id=7)

    make_agreement(line=line, counterparty=supplier, number="Д-3", amount="50000.00",
                   status="executed")
    make_agreement(line=line, counterparty=supplier, number="Д-4", amount="30000.00",
                   status="signed", direction="income")
    framework = make_agreement(line=line, counterparty=supplier, number="Д-5",
                               amount="0.00", status="signed", contract_type="framework")
    _pay(ContractPayment, framework, "20000.00", "closed", paid_at=PAID_AT)
    make_advance_payment(agreement=framework, amount="10000.00", status="awaiting_accounting")
    _pay(CompletionAct, framework, "5000.00", "draft")
    _pay(GoodsInvoice, framework, "7000.00", "closed", paid_at=PAID_AT)

    make_invoice(line=line, counterparty=supplier, name="Канцелярия", amount="15000.00",
                 status="approved")
    make_invoice(line=line, counterparty=supplier, name="Бумага", amount="5000.00",
                 status="paid")
    make_invoice(line=line, counterparty=supplier, name="Картриджи", amount="9000.00",
                 status="on_review")

    open_request = OldAccountable.objects.create(
        budget_line=line, amount=Decimal("50000.00"), goal="Расходники на объекте",
        status="awaiting_advance_report", accounting_paid=True, accounting_paid_by=7,
        accounting_paid_at=PAID_AT, accountable_user_id=7)
    OldReport.objects.create(accountable_funds_request=open_request, expense_name="Крепёж",
                             amount=Decimal("10000.00"), file_id="", approval_state="approved")
    OldReport.objects.create(accountable_funds_request=open_request, expense_name="Ветошь",
                             amount=Decimal("5000.00"), file_id="", approval_state="pending")
    OldAccountable.objects.create(budget_line=line, amount=Decimal("8000.00"), goal="Старое",
                                  status="closed", accountable_user_id=7)
    return admin, steel, signed, running, framework


def test_open_documents_move_in_their_status(company_context, tmp_path):
    slug = company_context["slug"]
    admin, steel, signed, running, framework = _world()
    paths = write_maps(tmp_path, {admin.id: "ОБ-А"}, {steel.id: "T-METAL"})

    text = migrate(slug, *paths)
    assert "документы:" in text

    agreements = {agr.ext_number: agr for agr in Agreement.objects.all()}
    assert set(agreements) == {"Д-1", "Д-2", "Д-5"}          # исполненный и поступление — нет
    active = agreements["Д-1"]
    assert (active.status, active.amount, active.is_migrated) == ("active", 400000, True)
    assert [(item.request_item.name, item.qty, item.amount) for item in
            active.items.order_by("request_item__line_no")] == [
        ("Балка", Decimal("3.000"), Decimal("300000.00")),
        ("Лист", Decimal("10.000"), Decimal("100000.00"))]
    tech = active.items.first().request_item.request
    assert (tech.status, tech.is_migrated) == ("approved", True)
    assert files.current_files("bpp.agreement", active.pk, "agreement")    # скан переехал

    # «На согласовании» — черновик, старый процесс отозван (D-B61-2).
    assert agreements["Д-2"].status == "draft"
    assert signoff.get_process_for(OldAgreement.SIGNOFF_SUBJECT_TYPE, running.id)["state"] \
        == "cancelled"
    # Открытый договор резервирует свои учтённые оплаты: 20 000 + 10 000 + 7 000.
    open_agr = agreements["Д-5"]
    assert (open_agr.is_open, open_agr.amount) == (True, None)
    assert open_agr.items.get().request_item.amount == Decimal("37000.00")

    by_basis = {(inv.basis, inv.amount): inv for inv in Invoice.objects.all()}
    paid = by_basis[("contract", Decimal("90000.00"))]
    assert (paid.status, paid.agreement_id) == ("paid", active.pk)
    assert [(line.amount) for line in paid.lines.order_by("request_item__line_no")] == [
        Decimal("67500.00"), Decimal("22500.00")]
    mark = paid.payments.get()
    assert (mark.amount, mark.pay_date.isoformat(), mark.pp_number) == (
        Decimal("90000.00"), "2026-09-01", "ПР-77")
    assert by_basis[("contract", Decimal("10000.00"))].is_advance
    assert by_basis[("contract", Decimal("10000.00"))].status == "to_pay"
    assert by_basis[("contract", Decimal("5000.00"))].status == "draft"
    assert by_basis[("contract", Decimal("7000.00"))].status == "paid"
    assert by_basis[("no_contract", Decimal("15000.00"))].status == "to_pay"
    assert by_basis[("no_contract", Decimal("9000.00"))].status == "draft"
    assert ("no_contract", Decimal("5000.00")) not in by_basis                 # оплачен — нет

    accountable = AccountableFundsRequest.objects.get()
    assert (accountable.status, accountable.amount) == ("awaiting_report", 50000)
    assert sorted(accountable.reports.values_list("approval_state", flat=True)) == [
        "approved", "draft"]

    # Технические заявки скрыты и утверждены — по одной на договор и счёт без договора.
    assert PurchaseRequest.objects.filter(is_migrated=True, status="approved").count() == 5
    assert links.targets("contracts.agreement", [running.id])[str(running.id)]


def test_second_run_adds_nothing(company_context, tmp_path):
    slug = company_context["slug"]
    admin, steel, *_ = _world()
    paths = write_maps(tmp_path, {admin.id: "ОБ-А"}, {steel.id: "T-METAL"})
    migrate(slug, *paths)
    counts = (Agreement.objects.count(), Invoice.objects.count(),
              PurchaseRequest.objects.count(), AccountableFundsRequest.objects.count(),
              MigrationLink.objects.count())
    migrate(slug, *paths)
    assert (Agreement.objects.count(), Invoice.objects.count(),
            PurchaseRequest.objects.count(), AccountableFundsRequest.objects.count(),
            MigrationLink.objects.count()) == counts
