"""Миграции ``ext_1c_ref``: уникальность (A7.3) и нижний регистр (D-S8-4).

Уникальность (``bpp/0018``, ``project/0002``): дубли непустых — стоп с
перечнем. Нижний регистр (``bpp/0020``, ``project/0003``): дубли БЕЗ учёта
регистра — стоп с перечнем (миграция ничего не удаляет), иначе значения
приводятся к нижнему регистру и накладывается ``CheckConstraint``; откат
проходит (данные остаются в нижнем регистре).
"""

from __future__ import annotations

import pytest
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor

GUID = "0f8fad5b-d9cb-469f-a165-70867728950e"
GUID_B = "7c9e6679-7425-40de-944b-e07fc1f90ae7"
GUID_C = "16fd2706-8baf-433b-82eb-8c7fada847da"

#: (аппка, шаг) → (миграция до, проверяемая миграция, модель).
CASES = {
    ("bpp", "unique"): ("0017_merge_stage5_a_b", "0018_ext_1c_unique", "Counterparty"),
    ("project", "unique"): ("0001_initial", "0002_ext_1c_unique", "Project"),
    ("bpp", "lower"): ("0019_holding_readers", "0020_ext_1c_lower", "Counterparty"),
    ("project", "lower"): ("0002_ext_1c_unique", "0003_ext_1c_lower", "Project"),
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


def _rows(app, apps, refs, start=0):
    model = apps.get_model(app, "Counterparty" if app == "bpp" else "Project")
    if app == "bpp":
        return [model(name=f"К{i}", kind="legal", country_code="KZ", reg_number=f"R{i}",
                      ext_1c_ref=ref) for i, ref in enumerate(refs, start)]
    return [model(code=f"П-{i}", name=f"П{i}", country_code="KZ", ext_1c_ref=ref)
            for i, ref in enumerate(refs, start)]


def _cleanup(app, before, model_name):
    apps = _migrate([(app, before)])
    apps.get_model(app, model_name).objects.all().delete()
    _migrate(_leaf(app))


@pytest.mark.parametrize("app", ["bpp", "project"])
@pytest.mark.django_db(transaction=True)
def test_duplicates_stop_the_migration_with_a_list(company_context, app):
    before, after, model_name = CASES[(app, "unique")]
    try:
        apps = _migrate([(app, before)])
        for row in _rows(app, apps, [GUID, GUID]):
            row.save()
        with pytest.raises(RuntimeError) as exc:
            _migrate([(app, after)])
        assert GUID in str(exc.value) and "2 записей" in str(exc.value)
    finally:
        _cleanup(app, before, model_name)


@pytest.mark.parametrize("app", ["bpp", "project"])
@pytest.mark.django_db(transaction=True)
def test_case_insensitive_duplicates_stop_the_lower_migration(company_context, app):
    """«ABC…» и «abc…» уникальность 0018/0002 пропустила; приведение к нижнему
    регистру их склеило бы — стоп с перечнем, обе записи на месте."""
    before, after, model_name = CASES[(app, "lower")]
    try:
        apps = _migrate([(app, before)])
        for row in _rows(app, apps, [GUID.upper(), GUID, GUID_B]):
            row.save()
        with pytest.raises(RuntimeError) as exc:
            _migrate([(app, after)])
        assert GUID in str(exc.value) and "2 записей" in str(exc.value)
        assert GUID_B not in str(exc.value)
        apps = _migrate([(app, before)])
        refs = sorted(apps.get_model(app, model_name).objects.values_list("ext_1c_ref", flat=True))
        assert refs == sorted([GUID.upper(), GUID, GUID_B])
    finally:
        _cleanup(app, before, model_name)


@pytest.mark.parametrize("app", ["bpp", "project"])
@pytest.mark.django_db(transaction=True)
def test_lower_migration_lowercases_refs_and_rolls_back(company_context, app, capsys):
    before, after, model_name = CASES[(app, "lower")]
    try:
        apps = _migrate([(app, before)])
        for row in _rows(app, apps, [GUID.upper(), GUID_B, ""]):
            row.save()
        apps = _migrate([(app, after)])
        model = apps.get_model(app, model_name)
        assert sorted(model.objects.values_list("ext_1c_ref", flat=True)) == ["", GUID, GUID_B]
        assert "приведено к нижнему регистру: 1" in capsys.readouterr().out
        # ограничение стоит: верхний регистр мимо сервиса не записать
        with pytest.raises(IntegrityError), transaction.atomic():
            _rows(app, apps, [GUID_C.upper()], start=10)[0].save()
        apps = _migrate([(app, before)])  # откат: ограничение снято, данные не трогаются
        model = apps.get_model(app, model_name)
        assert sorted(model.objects.values_list("ext_1c_ref", flat=True)) == ["", GUID, GUID_B]
        _rows(app, apps, [GUID_C.upper()], start=10)[0].save()  # после отката — снова можно
    finally:
        _cleanup(app, before, model_name)
