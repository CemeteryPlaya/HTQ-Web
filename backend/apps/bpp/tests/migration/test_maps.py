"""Карты переноса (B6.1, D-B61-3, D-B61-4): черновики предлагают то, что
уже есть в платформе; неполная карта останавливает перенос с перечнем."""

from __future__ import annotations

import pytest
from django.core.management import CommandError, call_command

from apps.bpp.services.migration import maps
from apps.bpp.tests import stage2 as s
from apps.contracts import interface as contracts
from apps.contracts.tests.helpers import (
    make_administrator,
    make_budget,
    make_country,
    make_line,
    make_program,
)

pytestmark = pytest.mark.django_db


def _contracts():
    kz = make_country()
    alga = make_administrator(country=kz, project_name="Объект П-015")
    aral = make_administrator(country=kz, project_name="Аральск")
    idle = make_administrator(country=kz, project_name="Без бюджета")
    metal = make_program(name="Металл", expense_item="Материалы", code="T-METAL")
    link = make_program(name="Связь", code="111")
    mobilization = make_program(name="Мобилизация", code="111")
    make_line(budget=make_budget(administrator=alga), program=metal)
    make_line(budget=make_budget(administrator=alga, period_year=2025), program=link)
    make_line(budget=make_budget(administrator=aral), program=mobilization)
    return alga, aral, idle, metal, link, mobilization


def test_drafts_propose_what_the_platform_already_has(company_context):
    s.metal()
    s.project("П-015")                         # «Объект П-015» — как у администратора
    alga, aral, idle, metal, link, mobilization = _contracts()
    snapshot = contracts.migration_snapshot()

    projects = {row["admin_id"]: row for row in maps.draft_projects(snapshot)}
    assert projects[alga.id]["project_code"] == "П-015"
    assert projects[aral.id]["project_code"] == f"П-{aral.id}"
    assert projects[aral.id]["country"] == "KZ"
    assert idle.id not in projects             # без бюджета — не переносится

    rows, conflicts = maps.draft_articles(snapshot, maps.article_index())
    articles = {row["program_id"]: row for row in rows}
    assert articles[metal.id]["article_code"] == "T-METAL"
    assert articles[metal.id]["used_by"] == "Объект П-015"
    # Код 111 у двух разных программ — по коду не сопоставить, только картой.
    assert articles[link.id]["article_code"] == articles[mobilization.id]["article_code"] == ""
    assert conflicts == ["Код программы 111 — у разных программ: Мобилизация, Связь"]


def test_incomplete_maps_stop_with_a_list(company_context):
    s.metal()
    alga, aral, idle, metal, link, mobilization = _contracts()
    snapshot = contracts.migration_snapshot()

    projects, errors = maps.check_projects([
        {"admin_id": str(alga.id), "project_code": "П-1", "manager_user_id": "7"},
        {"admin_id": str(aral.id), "project_code": "П-1", "manager_user_id": ""},
    ], snapshot)
    assert list(projects) == [alga.id] and projects[alga.id]["manager_user_id"] == 7
    assert errors == [f"Код проекта П-1 повторяется: администраторы {alga.id} и {aral.id}"]

    articles, errors = maps.check_articles([
        {"program_id": str(metal.id), "article_code": "T-METAL"},
        {"program_id": str(link.id), "article_code": ""},
    ], snapshot, maps.article_index())
    assert list(articles) == [metal.id]
    assert errors == ["Программа 111 Связь: не указана статья",
                      f"Карта статей: нет строки программы {mobilization.id} «111 Мобилизация»"]


def test_command_writes_drafts_and_refuses_an_incomplete_map(company_context, tmp_path):
    s.metal()
    alga, *_ = _contracts()
    slug = company_context["slug"]
    call_command("bpp_migrate_contracts", "--company", slug, "--draft-maps", str(tmp_path))
    assert {path.name for path in tmp_path.iterdir()} == {
        "projects.csv", "articles.csv", "conflicts.txt"}
    projects = maps.read_csv(tmp_path / "projects.csv", maps.PROJECT_COLUMNS)
    assert len(projects) == 2

    with pytest.raises(CommandError) as exc:
        call_command("bpp_migrate_contracts", "--company", slug,
                     "--projects-map", str(tmp_path / "projects.csv"),
                     "--articles-map", str(tmp_path / "articles.csv"))
    assert "карты неполные" in str(exc.value) and "не указана статья" in str(exc.value)
