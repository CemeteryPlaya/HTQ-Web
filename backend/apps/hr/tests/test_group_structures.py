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
    # Блок F: холдинг — posts 13 и people 13, но ДОКУМЕНТ говорит 12 → считаем штатные
    if structure.kind == "holding":
        actual_posts = [p for p in structure.posts if not p.is_system]
        system_titles = {p.title for p in structure.posts if p.is_system}
        actual_people = [p for p in structure.people if p.post not in system_titles]
        assert len(actual_posts) == posts
        assert len(actual_people) == people
        assert sum(p.is_system for p in structure.posts) == 1
    else:
        assert len(structure.posts) == posts
        assert len(structure.people) == people
    assert len({p.title for p in structure.posts}) == len(structure.posts)  # title unique в схеме
    assert len({p.weight for p in structure.posts}) == len(structure.posts)  # weight unique в схеме


def test_holding_has_four_managers_and_eight_serving_specialists():
    # Блок F: ОСУ — пятый is_manager (4 директора + ОСУ), но не serves_subsidiaries
    directors = [p for p in HOLDING.posts if p.is_manager and not p.is_system]
    serving = [p for p in HOLDING.posts if p.serves_subsidiaries]
    assert len(directors) == 4 and len(serving) == 8
    assert not {p.title for p in directors} & {p.title for p in serving}
    assert all(p.external_hierarchy == "inherit" for p in directors)
    participant = next(p for p in HOLDING.posts if p.is_system)
    assert participant.is_manager and participant.external_hierarchy == "inherit" and not participant.serves_subsidiaries


@pytest.mark.parametrize("structure, levels", [
    (HOLDING, {1, 2, 4}),      # N-3 пропущен (стр. 2); блок F: вес 0 ОСУ попадает в N-1 (решение 1)
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
    # Блок F: для холдинга единственная должность без начальника — ОСУ
    if structure.kind == "holding":
        assert heads[0].title == "Участник (ОСУ)"
    else:
        assert heads[0].title == "Директор"
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
            # Блок F: стр. 1: ОСУ над ГД
            ("Генеральный директор", "Участник (ОСУ)"),
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
    """Правка Садыева: в ДО «Директор», не «Генеральный директор».

    Блок F: в холдинге главная должность — Участник (ОСУ), не ГД, а в ДО
    остаётся «Директор» (не ГД, который только в холдинге)."""
    for s in (HTQ, HTS, KEG):
        head = next(p for p in s.posts if p.reports_to is None)
        assert head.title == "Директор"
        # ГД в ДО нет — проверяем, чтобы ошибочно привезённый ГД был замечен.
        assert "Генеральный директор" not in {p.title for p in s.posts}
    # Блок F: в холдинге главная должность — Участник (ОСУ), не ГД
    assert next(p for p in HOLDING.posts if p.reports_to is None).title == "Участник (ОСУ)"
    # ГД в холдинге есть, но не как главная (подчинён ОСУ).
    assert any(p.title == "Генеральный директор" for p in HOLDING.posts)


def test_holding_directorates_are_directorates():
    # Блок F: ОСУ исключаем — это орган владельцев, не дирекция
    types = [u.unit_type for u in HOLDING.units if u.path not in ("upr", "osu")]
    assert types == ["directorate"] * 3


def test_functional_links_are_exactly_the_dashed_lines():
    assert HOLDING.functional_links == (
        ("Главный бухгалтер", "ГИП"),
        ("ГИП", "Менеджер по кадрам"),
        ("Менеджер ПТО и КК", "Менеджер по закупкам"),
    )
    assert all(s.functional_links == () for s in (HTQ, HTS, KEG))


def test_participant_is_the_only_system_post_and_sits_on_top():
    """ОСУ — единственная системная должность, с весом 0 (вершина шкалы),
    в своём подразделении, и оно есть только у холдинга."""
    system = [p for p in HOLDING.posts if p.is_system]
    assert [p.title for p in system] == ["Участник (ОСУ)"]
    assert system[0].weight == 0 and system[0].unit == "osu"
    assert min(p.weight for p in HOLDING.posts) == 0
    for kind in ("construction", "it", "service"):
        assert not any(p.is_system for p in gs.STRUCTURES[kind].posts)
        assert not any(u.path == "osu" for u in gs.STRUCTURES[kind].units)


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


def test_participant_unit_name_matches_the_service_definition():
    """Имя подразделения ОСУ определено в двух местах: в справочнике структур
    (group_structures) и в сервисе (participant_service). Расхождение будет
    молчаливым: сид пишет первое, ensure_participant тут же переписывает вторым.
    
    Прецедент: LEVELS в миграции 0024 и в group_structures.py — тест
    test_levels_match_the_migration_seed держит их в синхронизме."""
    from apps.hr.services import participant_service
    
    # Имя подразделения в структуре должно совпадать с именем в сервисе.
    gs_unit = next(u for u in HOLDING.units if u.path == "osu")
    assert gs_unit.name == participant_service.PARTICIPANT_UNIT_NAME, (
        f"Расхождение имён: '{gs_unit.name}' vs '{participant_service.PARTICIPANT_UNIT_NAME}' — "
        f"сид и сервис не совпадают"
    )
    assert gs_unit.path == participant_service.PARTICIPANT_UNIT_PATH
