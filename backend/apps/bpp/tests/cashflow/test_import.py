"""Импорт книги CashFlow в модуль (B6.2): те же суммы, что старый импорт в
«Договоры»; бюджет — черновик для ФД (D-B62-2); только добавляет
(D-B62-1); книга после переноса «Договоров» ничего не удваивает (D-B62-4)."""

from __future__ import annotations

import io
from decimal import Decimal

import pytest
from django.core.management import call_command
from django.db.models import Sum

from apps.bpp.models import Agreement, Budget, Invoice
from apps.bpp.services.budget import budgets
from apps.bpp.services.cashflow import maps
from apps.bpp.tests import stage2 as s
from apps.bpp.tests.migration import common as migration
from apps.bpp.tests.test_files import memory_storage  # noqa: F401  (фикстура)
from apps.contracts.models import Administrator as OldAdmin
from apps.contracts.models import Agreement as OldAgreement
from apps.contracts.models import ContractPayment
from apps.contracts.models import Invoice as OldInvoice
from apps.contracts.models import Program as OldProgram
from apps.contracts.services import cashflow_import as old_registry
from apps.contracts.services import cashflow_operations_import as old_ops
from apps.contracts.tests.test_cashflow_operations_import import (
    ARALSK,
    DAMONA,
    build_book,
    by_agreement,
    op_row,
)
from apps.project import interface as projects

from .test_workbook import REGISTRY

pytestmark = pytest.mark.django_db
ACTOR = migration.ACTOR
OPS = [by_agreement(), by_agreement(), op_row(amount=250000.75),
       op_row(budget=3011, goods="Щебень")]
ARTICLES = {(ARALSK, "3020"): "T-METAL", (ARALSK, "3026"): "T-CABLE",
            (DAMONA, "3011"): "T-DESIGN"}
PROJECTS = {ARALSK: "ARL", DAMONA: "DMN"}


def _setup(tmp_path):
    s.user(ACTOR)
    s.metal(), s.design(), s.article("T-CABLE", "Кабельная продукция", "supply")
    path = build_book(tmp_path, ops_rows=OPS, registry_rows=REGISTRY)
    projects_csv, articles_csv = tmp_path / "p.csv", tmp_path / "a.csv"
    maps.write_csv(projects_csv, maps.PROJECT_COLUMNS, [
        {"administrator": name, "project_code": code, "country": "KZ", "manager_user_id": ""}
        for name, code in PROJECTS.items()])
    maps.write_csv(articles_csv, maps.ARTICLE_COLUMNS, [
        {"administrator": admin, "program_code": code, "program_name": "",
         "article_code": article} for (admin, code), article in ARTICLES.items()])
    return path, projects_csv, articles_csv


def _import(slug, path, projects_csv, articles_csv, *extra) -> str:
    out = io.StringIO()
    call_command("bpp_import_cashflow", path, "--company", slug, "--projects-map",
                 str(projects_csv), "--articles-map", str(articles_csv), "--actor", str(ACTOR),
                 *extra, stdout=out)
    return out.getvalue()


def _approve_all(slug):
    fd = s.actor(slug, 999, superuser=True)
    for budget in Budget.objects.filter(status="draft"):
        budgets.approve(fd, budget.id, expected_version=None, notify_parties=False)


def _counts():
    return Agreement.objects.count(), Invoice.objects.count(), Budget.objects.count()


def test_draft_budget_first_then_the_same_sums_as_the_old_import(company_context, tmp_path):
    slug = company_context["slug"]
    path, projects_csv, articles_csv = _setup(tmp_path)

    # Первый прогон: бюджеты — черновики для ФД, документы ждут утверждения.
    text = _import(slug, path, projects_csv, articles_csv)
    assert "Бюджеты-черновики: 2" in text and "ждут утверждения бюджета: 7" in text
    assert set(Budget.objects.values_list("status", flat=True)) == {"draft"}
    assert not Agreement.objects.exists() and not Invoice.objects.exists()

    _approve_all(slug)
    _import(slug, path, projects_csv, articles_csv)

    # Старый импорт той же книги — в «Договоры» (та же схема компании).
    old_registry.run_import(path)
    old_ops.run_import(path)

    standard = Agreement.objects.filter(is_open=False).aggregate(t=Sum("amount"))["t"]
    old_standard = (OldAgreement.objects.exclude(contract_type="framework")
                    .aggregate(t=Sum("amount"))["t"])
    assert standard == old_standard == Decimal("1550000.50")
    by_contract = Invoice.objects.filter(basis="contract").aggregate(t=Sum("amount"))["t"]
    assert by_contract == ContractPayment.objects.aggregate(t=Sum("amount"))["t"] \
        == Decimal("2832000.00")
    without = Invoice.objects.filter(basis="no_contract").aggregate(t=Sum("amount"))["t"]
    assert without == OldInvoice.objects.aggregate(t=Sum("amount"))["t"] == Decimal("350000.75")
    assert set(Invoice.objects.values_list("status", flat=True)) == {"paid"}
    # Лимиты: сумма программ статьи = сумма строк старого бюджета этих программ.
    aralsk = Budget.objects.get(project_id=projects.project_ids_by_code(["ARL"])["ARL"])
    assert sum(line.limit_amount for line in aralsk.versions.get(version_no=1).lines.all()) \
        == Decimal("21414971.00") + Decimal("11599916.00")
    # Открытый договор резервирует свои оплаты из книги.
    open_agr = Agreement.objects.get(is_open=True)
    assert open_agr.items.get().request_item.amount == Decimal("2832000.00")

    counts = _counts()
    _import(slug, path, projects_csv, articles_csv)          # повтор — ничего нового
    assert _counts() == counts


def _sheet(path, title) -> list[dict]:
    import openpyxl

    rows = list(openpyxl.load_workbook(path, read_only=True)[title].iter_rows(values_only=True))
    return [dict(zip(rows[0], row)) for row in rows[1:]]


def test_report_names_book_contracts_and_articles_readably(company_context, tmp_path):
    """Репетиция на стенде 30.09: у двух договоров книги один номер «1» — в
    отчёте они различаются LARK; расхождение лимита — по коду статьи, а не id."""
    slug = company_context["slug"]
    path, projects_csv, articles_csv = _setup(tmp_path)
    report = tmp_path / "first.xlsx"
    _import(slug, path, projects_csv, articles_csv, "--report", str(report))
    waiting = {row["old_id"] for row in _sheet(report, "Не перенесено")
               if row["kind"] == "договор"}
    assert {"1 (LARK L-1)", "1 (LARK L-2)"} <= waiting

    _approve_all(slug)
    aralsk = Budget.objects.get(project_id=projects.project_ids_by_code(["ARL"])["ARL"])
    aralsk.versions.get(version_no=1).lines.filter(
        article_id=s.metal().id).update(limit_amount=Decimal("1.00"))
    report = tmp_path / "second.xlsx"
    _import(slug, path, projects_csv, articles_csv, "--report", str(report))
    assert [row["key"] for row in _sheet(report, "Расхождения с книгой")] == ["ARL / T-METAL"]


def test_book_after_the_contracts_migration_adds_nothing(company_context, tmp_path):
    """Книга уже в «Договорах» (старый импорт) и перенесена B6.1 — импорт той
    же книги в модуль узнаёт всё по LARK и отпечаткам строк."""
    slug = company_context["slug"]
    path, projects_csv, articles_csv = _setup(tmp_path)
    old_registry.run_import(path)
    old_ops.run_import(path)
    admins = {row.project_name: row.id for row in OldAdmin.objects.all()}
    programs = {}
    for admin_name, admin_id in admins.items():
        for program in OldProgram.objects.filter(budget_lines__budget__administrator_id=admin_id):
            programs[program.id] = ARTICLES[(admin_name, program.code)]
    migration.migrate(slug, *migration.write_maps(
        tmp_path, {admins[name]: code for name, code in PROJECTS.items()}, programs))
    _approve_all(slug)
    counts = _counts()

    text = _import(slug, path, projects_csv, articles_csv)
    assert _counts() == counts
    assert "документы: 0" in text
