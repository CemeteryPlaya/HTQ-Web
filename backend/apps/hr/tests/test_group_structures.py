"""Справочник оргструктур группы обязан совпадать с документом 10.09.2026.

Это не «тест на константы»: справочник сеется в четыре схемы и по нему
смотрят стенд глазами. Числа взяты со стр. 2–5 документа — «Руководители —
4, Менеджеры — 8, всего 12», «Руководители — 1, Специалисты — 3, всего 4».
"""

from __future__ import annotations

import importlib

import pytest

from apps.hr.management import group_structures as gs

migration = importlib.import_module("apps.hr.migrations.0024_seed_level_thresholds")

HOLDING = gs.STRUCTURES["holding"]
HTQ = gs.STRUCTURES["construction"]
HTS = gs.STRUCTURES["it"]
KEG = gs.STRUCTURES["service"]


def test_levels_match_the_migration_seed():
    assert gs.LEVELS == migration.LEVELS


def test_one_structure_per_company_kind():
    from apps.companies.models import CompanyKind  # тесты вне сторожа изоляции
    assert set(gs.STRUCTURES) == {k.value for k in CompanyKind} - {"regional"}
    with pytest.raises(gs.UnknownStructure, match="regional"):
        gs.structure_for("regional")


@pytest.mark.parametrize("structure, posts, people", [
    (HOLDING, 12, 12), (HTQ, 4, 4), (HTS, 4, 4), (KEG, 4, 4),
])
def test_headcount_matches_the_document(structure, posts, people):
    assert len(structure.posts) == posts
    assert len(structure.people) == people
    assert len({p.title for p in structure.posts}) == posts  # title unique в схеме
    assert len({p.weight for p in structure.posts}) == posts  # weight unique в схеме


def test_holding_has_four_managers_and_eight_serving_specialists():
    directors = [p for p in HOLDING.posts if p.is_manager]
    serving = [p for p in HOLDING.posts if p.serves_subsidiaries]
    assert len(directors) == 4 and len(serving) == 8
    assert not {p.title for p in directors} & {p.title for p in serving}
    assert all(p.external_hierarchy == "inherit" for p in directors)


@pytest.mark.parametrize("structure, levels", [
    (HOLDING, {1, 2, 4}),      # N-3 пропущен (стр. 2)
    (HTQ, {1, 2, 4}),          # N-3 пропущен (стр. 3)
    (HTS, {1, 2, 3, 4}),       # стр. 4
    (KEG, {1, 3, 4}),          # N-2 пуст (стр. 5)
])
def test_levels_used_by_each_structure(structure, levels):
    assert {gs.level_for(p.weight) for p in structure.posts} == levels


@pytest.mark.parametrize("structure", [HOLDING, HTQ, HTS, KEG])
def test_every_reference_resolves(structure):
    titles = {p.title for p in structure.posts}
    paths = {u.path for u in structure.units}
    heads = [p for p in structure.posts if p.reports_to is None]
    assert len(heads) == 1, "ровно одна должность без начальника — глава компании"
    for post in structure.posts:
        assert post.unit in paths
        assert post.reports_to is None or post.reports_to in titles
    for person in structure.people:
        assert person.post in titles
    for a, b in structure.functional_links:
        assert a in titles and b in titles and a != b
    for path, title in structure.managers.items():
        assert path in paths and title in titles
        # Руководитель обязан работать в своём подразделении (инвариант дерева).
        assert next(p for p in structure.posts if p.title == title).unit == path


def test_direct_chain_matches_the_document():
    """Полная цепочка подчинения каждой структуры — литералами из документа.

    ``test_every_reference_resolves`` проверяет, что ссылка не битая; этот —
    что она ведёт туда, куда ведёт документ (стр. 2–5). Без него подмена
    начальника на другого существующего осталась бы незамеченной: ссылка
    валидна, а структура уже не та, что утвердило руководство.
    """
    expected = {
        "holding": {
            ("Финансовый директор", "Генеральный директор"),
            ("Технический директор", "Генеральный директор"),
            ("Операционный директор", "Генеральный директор"),
            ("Главный бухгалтер", "Финансовый директор"),
            # Поправка заказчика от 16.09.2026 (см. план блока E): эти две
            # пары называют должности так, как решил заказчик, а не дословным
            # текстом документа («Кадровый бухгалтер» и «Системный
            # администратор» соответственно).
            ("Бухгалтер", "Финансовый директор"),
            ("Экономист-аналитик", "Финансовый директор"),
            ("ГИП", "Технический директор"),
            ("Менеджер ПТО и КК", "Технический директор"),
            ("Менеджер по кадрам", "Операционный директор"),
            ("Менеджер по закупкам", "Операционный директор"),
            ("Специалист технической поддержки", "Операционный директор"),
        },
        "construction": {
            ("Руководитель проекта", "Директор"),
            ("Начальник участка", "Руководитель проекта"),
            ("Инженер по ОТ и ТБ", "Руководитель проекта"),
        },
        "it": {
            ("Senior Full-stack developer", "Директор"),
            ("Middle Full-stack developer", "Директор"),
            ("Junior Full-stack developer", "Директор"),
        },
        "service": {
            ("Диспетчер", "Директор"),
            ("Механик", "Директор"),
            ("Водитель-оператор", "Директор"),
        },
    }
    for kind, pairs in expected.items():
        actual = {(p.title, p.reports_to) for p in gs.STRUCTURES[kind].posts
                  if p.reports_to is not None}
        assert actual == pairs, kind


def test_subsidiary_heads_are_directors_not_general_directors():
    """Правка Садыева: в ДО «Директор», не «Генеральный директор»."""
    for s in (HTQ, HTS, KEG):
        head = next(p for p in s.posts if p.reports_to is None)
        assert head.title == "Директор"
    assert next(p for p in HOLDING.posts if p.reports_to is None).title == "Генеральный директор"


def test_holding_directorates_are_directorates():
    assert [u.unit_type for u in HOLDING.units if u.path != "upr"] == ["directorate"] * 3


def test_functional_links_are_exactly_the_dashed_lines():
    assert HOLDING.functional_links == (
        ("Главный бухгалтер", "ГИП"),
        ("ГИП", "Менеджер по кадрам"),
        ("Менеджер ПТО и КК", "Менеджер по закупкам"),
    )
    assert all(s.functional_links == () for s in (HTQ, HTS, KEG))


def test_emails_are_unique_across_the_whole_group():
    """Учётки платформы общие на группу — почта не может повториться."""
    emails = [gs.email_for(p) for s in gs.STRUCTURES.values() for p in s.people]
    assert len(emails) == len(set(emails))


def test_substitution_matrix_matches_the_document():
    """Десять строк HR-FRM-006, литералами. Одиннадцатая («Системный
    администратор» → «Внутригрупповой ИТ-подрядчик») намеренно отсутствует:
    подрядчик — не должность."""
    actual = {(r.position, r.kind, r.substitute) for r in HOLDING.substitutions}
    assert actual == {
        ("Генеральный директор", "primary", "Операционный директор"),
        ("Генеральный директор", "reserve", "Финансовый директор"),
        ("Финансовый директор", "primary", "Главный бухгалтер"),
        ("Финансовый директор", "reserve", "Экономист-аналитик"),
        ("Технический директор", "primary", "Менеджер ПТО и КК"),
        ("Технический директор", "reserve", "Операционный директор"),
        ("Операционный директор", "primary", "Менеджер по кадрам"),
        ("Операционный директор", "reserve", "Финансовый директор"),
        ("Главный бухгалтер", "primary", "Бухгалтер"),
        ("Главный бухгалтер", "reserve", "Экономист-аналитик"),
    }
    assert not any(r.position == "Специалист технической поддержки"
                   for r in HOLDING.substitutions)


def test_every_substitution_names_real_positions_of_its_structure():
    for structure in gs.STRUCTURES.values():
        titles = {p.title for p in structure.posts}
        for row in structure.substitutions:
            assert row.position in titles, (structure.kind, row.position)
            assert row.substitute in titles, (structure.kind, row.substitute)
            assert row.position != row.substitute


def test_only_the_holding_has_a_substitution_matrix():
    """Документ описывает матрицу только для управляющей компании."""
    for kind in ("construction", "it", "service"):
        assert gs.STRUCTURES[kind].substitutions == ()


def test_document_titles_are_preserved_where_they_differ():
    """Расхождение названий (roadmap §8.2) обязано быть видимым: пока
    руководство не ответило, оригинал документа хранится рядом."""
    differing = {(r.document_title, r.substitute) for r in HOLDING.substitutions
                 if r.document_title != r.substitute}
    assert differing == {
        ("Финансовый директор (CFO)", "Финансовый директор"),
        ("Экономист", "Экономист-аналитик"),
        ("Специалист ПТО", "Менеджер ПТО и КК"),
        ("HR-специалист", "Менеджер по кадрам"),
    }
