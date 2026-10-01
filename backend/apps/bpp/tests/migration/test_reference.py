"""Справочники и бюджеты переноса (B6.1, задача 4, D-B61-4, D-B61-5)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.core.management import CommandError

from apps.bpp.models import Budget, Counterparty, MigrationLink
from apps.bpp.services.migration import reference
from apps.bpp.services.migration.report import MigrationReport
from apps.bpp.tests import stage2 as s
from apps.contracts import interface as contracts
from apps.contracts.tests.helpers import (
    make_administrator,
    make_budget,
    make_counterparty,
    make_country,
    make_line,
    make_program,
)
from apps.project import interface as projects

from .common import ACTOR, migrate, write_maps

pytestmark = pytest.mark.django_db


def _world():
    s.user(ACTOR), s.user(7)
    metal, design = s.metal(), s.design()
    kz = make_country()
    alpha = make_administrator(country=kz, project_name="Объект А")
    beta = make_administrator(country=kz, project_name="Объект Б")
    steel = make_program(name="Металл", code="3011")
    docs = make_program(name="Документация", code="3012")
    y2025 = make_budget(administrator=alpha, period_year=2025, approval_state="approved")
    y2026 = make_budget(administrator=alpha, period_year=2026, approval_state="approved")
    usd = make_budget(administrator=alpha, period_year=2026, currency="USD",
                      approval_state="approved")
    make_line(budget=y2025, program=steel, amount="1000000.00")
    make_line(budget=y2025, program=docs, amount="500000.00")
    make_line(budget=y2026, program=steel, amount="2000000.00")
    make_line(budget=usd, program=steel, amount="100000.00")
    make_line(budget=make_budget(administrator=beta, period_year=2026), program=steel,
              amount="300000.00")
    make_counterparty(country=kz, bin_iin="123456789012", name="ТОО «Альфа»")
    make_counterparty(country=kz, bin_iin="990101300123", name="ИП Бета", status="blocked")
    return alpha, beta, steel, docs, usd, metal, design


def _limits(project_code: str) -> tuple[str, dict[str, Decimal]]:
    project_id = projects.project_ids_by_code([project_code])[project_code]
    budget = Budget.objects.get(project_id=project_id)
    lines = budget.versions.get(version_no=1).lines.all()
    return budget.status, {str(line.article_id): line.limit_amount for line in lines}


def test_projects_counterparties_and_summed_budgets(company_context, tmp_path):
    slug = company_context["slug"]
    alpha, beta, steel, docs, usd, metal, design = _world()
    known = Counterparty.objects.create(name="ТОО «Альфа» (уже в модуле)", kind="legal",
                                        country_code="KZ", reg_number="123456789012")
    paths = write_maps(tmp_path, {alpha.id: "ОБ-А", beta.id: "ОБ-Б"},
                       {steel.id: "T-METAL", docs.id: "T-DESIGN"}, managers={alpha.id: 7})

    text = migrate(slug, *paths)
    assert "Перенос выполнен" in text

    assert projects.member_user_ids(projects.project_ids_by_code(["ОБ-А"])["ОБ-А"]) == [7]
    # Годы суммируются по статье; USD — не переносится (D-06).
    status, limits = _limits("ОБ-А")
    assert status == "approved"
    assert limits == {str(metal.id): Decimal("3000000.00"), str(design.id): Decimal("500000.00")}
    # Без утверждённых лет — бюджет-черновик.
    assert _limits("ОБ-Б") == ("draft", {str(metal.id): Decimal("300000.00")})

    assert Counterparty.objects.filter(reg_number="123456789012").get() == known
    beta_cp = Counterparty.objects.get(reg_number="990101300123")
    assert (beta_cp.kind, beta_cp.status) == ("ip", "blocked")

    links_before = MigrationLink.objects.count()
    migrate(slug, *paths)                              # повтор — ничего нового
    assert MigrationLink.objects.count() == links_before
    assert Budget.objects.count() == 2 and Counterparty.objects.count() == 2


def test_usd_budget_is_reported_not_migrated():
    report = MigrationReport()
    snapshot = {"budgets": [
        {"id": 1, "administrator_id": 5, "period_year": 2026, "currency": "USD",
         "approval_state": "approved", "lines": []},
        {"id": 2, "administrator_id": 5, "period_year": 2025, "currency": "KZT",
         "approval_state": "draft", "lines": [{"program_id": 3, "amount": Decimal("10")}]},
        {"id": 3, "administrator_id": 5, "period_year": 2026, "currency": "KZT",
         "approval_state": "approved", "lines": [{"program_id": 3, "amount": Decimal("20")}]},
    ]}
    plan = reference.budget_limits(snapshot, {3: {"id": "art"}}, report)
    assert plan == {5: {"approved": True, "years": [2026], "limits": {"art": Decimal("20")}}}
    assert [row["old_id"] for row in report.rows["Не перенесено"]] == [1, 2]


def test_dry_run_writes_nothing_and_an_own_budget_stops(company_context, tmp_path):
    slug = company_context["slug"]
    alpha, beta, steel, docs, usd, metal, design = _world()
    paths = write_maps(tmp_path, {alpha.id: "ОБ-А", beta.id: "ОБ-Б"},
                       {steel.id: "T-METAL", docs.id: "T-DESIGN"})

    assert "Проверка без записи" in migrate(slug, *paths, "--dry-run")
    assert not projects.project_ids_by_code(["ОБ-А", "ОБ-Б"])
    assert not MigrationLink.objects.exists()

    # У проекта уже свой бюджет, заведённый не переносом, — стоп и откат.
    own = s.project("ОБ-Б")
    s.approved_budget(slug, own, {metal: 1000})
    with pytest.raises(CommandError) as exc:
        migrate(slug, *paths)
    assert "уже есть бюджет" in str(exc.value)
    assert not projects.project_ids_by_code(["ОБ-А"])
    assert contracts.migration_snapshot()["budgets"]            # «Договоры» не тронуты
