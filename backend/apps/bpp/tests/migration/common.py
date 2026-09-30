"""Общее для тестов переноса (B6.1): данные «Договоров» и запуск команды с
заполненными картами."""

from __future__ import annotations

import io
from pathlib import Path

from django.core.management import call_command

from apps.bpp.services.migration import maps
from apps.contracts import interface as contracts

ACTOR = 901


def write_maps(folder: Path, projects: dict[int, str], articles: dict[int, str],
               managers: dict[int, int] | None = None) -> tuple[Path, Path]:
    """Карты из словарей ``{admin_id: код проекта}`` и ``{program_id: код
    статьи}`` — как их вернул бы ФД."""
    managers = managers or {}
    snapshot = contracts.migration_snapshot()
    admins = {row["id"]: row for row in snapshot["administrators"]}
    programs = {row["id"]: row for row in snapshot["programs"]}
    project_path, article_path = folder / "projects.csv", folder / "articles.csv"
    maps.write_csv(project_path, maps.PROJECT_COLUMNS, [{
        "admin_id": admin_id, "project_name": admins[admin_id]["project_name"], "country": "KZ",
        "project_code": code, "manager_user_id": managers.get(admin_id, ""),
    } for admin_id, code in projects.items()])
    maps.write_csv(article_path, maps.ARTICLE_COLUMNS, [{
        "program_id": program_id, "program_code": programs[program_id]["code"],
        "program_name": programs[program_id]["name"],
        "expense_item": programs[program_id]["expense_item"], "used_by": "",
        "article_code": code,
    } for program_id, code in articles.items()])
    return project_path, article_path


def migrate(slug: str, project_path: Path, article_path: Path, *extra: str) -> str:
    out = io.StringIO()
    call_command("bpp_migrate_contracts", "--company", slug, "--projects-map", str(project_path),
                 "--articles-map", str(article_path), "--actor", str(ACTOR), *extra, stdout=out)
    return out.getvalue()
