"""Миграции ограничения ``ext_1c_ref`` (A7.3): дубли непустых — стоп с перечнем."""

from __future__ import annotations

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

GUID = "0f8fad5b-d9cb-469f-a165-70867728950e"

CASES = {
    "bpp": ("0017_merge_stage5_a_b", "0018_ext_1c_unique", "Counterparty"),
    "project": ("0001_initial", "0002_ext_1c_unique", "Project"),
}


def _migrate(targets):
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(targets)
    executor.loader.build_graph()
    return executor.loader.project_state(targets).apps


def _leaf(app):
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    return [key for key in executor.loader.graph.leaf_nodes() if key[0] == app]


def _rows(app, apps):
    model = apps.get_model(app, CASES[app][2])
    if app == "bpp":
        return [model(name=f"К{i}", kind="legal", country_code="KZ", reg_number=f"R{i}",
                      ext_1c_ref=GUID) for i in range(2)]
    return [model(code=f"П-{i}", name=f"П{i}", country_code="KZ", ext_1c_ref=GUID)
            for i in range(2)]


@pytest.mark.parametrize("app", ["bpp", "project"])
@pytest.mark.django_db(transaction=True)
def test_duplicates_stop_the_migration_with_a_list(company_context, app):
    before, after, _ = CASES[app]
    try:
        apps = _migrate([(app, before)])
        for row in _rows(app, apps):
            row.save()
        with pytest.raises(RuntimeError) as exc:
            _migrate([(app, after)])
        assert GUID in str(exc.value) and "2 записей" in str(exc.value)
    finally:
        apps = _migrate([(app, before)])
        apps.get_model(app, CASES[app][2]).objects.all().delete()
        _migrate(_leaf(app))
