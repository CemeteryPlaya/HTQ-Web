"""Бэкфилл ``Equipment.category``: свободный текст → строки справочника.

Единственный кусок этой ветки, который МОЖЕТ ПОТЕРЯТЬ ДАННЫЕ, если написан
неверно, и единственный, который обычные тесты не задевают: тестовая база
создаётся пустой, так что ``RunPython`` в миграции 0008 отрабатывает на нуле
строк и ничего не доказывает.

Поэтому здесь миграции откатываются до 0007, в старую схему пишутся строки с
текстовой категорией, и накат 0008 проверяется на них.

``transaction=True`` обязателен: миграции это DDL, внутри обёрнутой
транзакции pytest-django они не выполнятся. По той же причине состояние базы
не откатывается само — за возврат на последнюю миграцию отвечает ``finally``
в фикстуре, иначе следующие тесты сессии получили бы базу в схеме 0007.
"""

from __future__ import annotations

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

BEFORE = ("tasks", "0007_work_references")
AFTER = ("tasks", "0008_equipment_category_fk")


def _migrate(target):
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate([target])
    executor.loader.build_graph()
    return executor.loader.project_state([target]).apps


@pytest.fixture
def at_0007():
    """Откатить схему до 0007 и вернуть её обратно после теста."""
    try:
        yield _migrate(BEFORE)
    finally:
        # На последнюю миграцию аппки, а не на AFTER: иначе база осталась бы
        # без блоков, роудмапа и ресурсов, и всё, что запустится следом,
        # упало бы на отсутствующих таблицах.
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(
            [key for key in executor.loader.graph.leaf_nodes() if key[0] == "tasks"]
        )


@pytest.mark.django_db(transaction=True)
def test_backfill_moves_text_categories_into_the_reference(at_0007):
    Equipment = at_0007.get_model("tasks", "Equipment")
    Equipment.objects.create(name="Кара K-1", category="Спецтехника")
    Equipment.objects.create(name="Кара K-2", category="Спецтехника")
    Equipment.objects.create(name="Кран", category="Подъёмная")
    Equipment.objects.create(name="Без категории", category=None)

    apps = _migrate(AFTER)
    Equipment = apps.get_model("tasks", "Equipment")
    EquipmentCategory = apps.get_model("tasks", "EquipmentCategory")

    # Одна строка справочника на каждое различное имя, а не на каждую машину.
    assert set(EquipmentCategory.objects.values_list("name", flat=True)) \
        == {"Спецтехника", "Подъёмная"}

    special = EquipmentCategory.objects.get(name="Спецтехника")
    assert special.slug == "spetstehnika"
    assert set(Equipment.objects.filter(category=special)
               .values_list("name", flat=True)) == {"Кара K-1", "Кара K-2"}
    # Пустая категория остаётся пустой — выдумывать её не из чего.
    assert Equipment.objects.get(name="Без категории").category_id is None


@pytest.mark.django_db(transaction=True)
def test_backfill_collapses_case_and_whitespace_variants(at_0007):
    """«Спецтехника», «спецтехника » и «СПЕЦТЕХНИКА» — один тип.

    Ради этого справочник и заведён: по свободному тексту «нужно 2 кары»
    не сослаться, если в базе три написания одного слова.
    """
    Equipment = at_0007.get_model("tasks", "Equipment")
    for index, raw in enumerate(("Спецтехника", "спецтехника ", " СПЕЦТЕХНИКА")):
        Equipment.objects.create(name=f"Машина {index}", category=raw)

    apps = _migrate(AFTER)
    EquipmentCategory = apps.get_model("tasks", "EquipmentCategory")
    Equipment = apps.get_model("tasks", "Equipment")

    assert EquipmentCategory.objects.count() == 1
    row = EquipmentCategory.objects.get()
    # Показываемое имя — как ввели в первый раз, без обрезки регистра.
    assert row.name == "Спецтехника"
    assert Equipment.objects.filter(category=row).count() == 3


@pytest.mark.django_db(transaction=True)
def test_backfill_gives_colliding_slugs_distinct_suffixes(at_0007):
    """Разные имена, дающие один слаг, не должны схлопнуться в одну строку:
    ``slug`` уникален, и без суффикса миграция упала бы на индексе."""
    Equipment = at_0007.get_model("tasks", "Equipment")
    Equipment.objects.create(name="A", category="Кран")
    Equipment.objects.create(name="B", category="К Р А Н")

    apps = _migrate(AFTER)
    EquipmentCategory = apps.get_model("tasks", "EquipmentCategory")
    slugs = sorted(EquipmentCategory.objects.values_list("slug", flat=True))
    assert len(slugs) == 2
    assert len(set(slugs)) == 2
