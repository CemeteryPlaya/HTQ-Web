"""Мост «кадровые уровни -> роли»: доказуемость переноса (блок I, задача 1).

Каждый тест здесь — одна из обязательных проверок брифа задачи
(``.superpowers/sdd/2026-09-17-block-i-single-rbac/task-1-brief.md``).
Три неоднозначных решения перевода (``view`` vs ``view.all``, ``transfer``,
чужой ключ ``contracts.*``) объяснены комментариями у
``apps.hr.legacy_roles.KEY_TO_NODE`` и в отчёте той же задачи; здесь их не
повторяем, а проверяем последствия.

``apps.access`` импортирует ``apps.hr`` напрямую (не через ``interface``) —
это нормально ИМЕННО в ``tests/``: ``apps/core/tests/test_app_isolation.py``
каталоги тестов не сканирует (см. его же докстринг и ``apps/access/tests/
conftest.py``, который делает то же самое ради ``employee_with_position``).
"""

from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest
from django.apps import apps as django_apps

from apps.access import depth, registry
from apps.access.models import Role, RolePermission
from apps.hr import legacy_roles
from apps.hr import permissions as legacy

migration = importlib.import_module("apps.access.migrations.0005_seed_hr_level_roles")


def _seed() -> None:
    """Прогнать сид миграции 0005 как обычную функцию — тот же приём, что
    ``apps/hr/tests/test_level_seed_migration.py`` использует для 0024:
    ``seed(apps, schema_editor)`` в этой миграции ``schema_editor`` не
    читает вовсе, поэтому вместо заглушки достаточно ``None``."""
    migration.seed(django_apps, SimpleNamespace())


# ── Таблица соответствия (Step 1, KEY_TO_NODE) ──────────────────────────────


def test_every_legacy_key_is_mapped():
    """Каждый ключ ``apps.hr.permissions.ALL_KEYS`` имеет соответствие —
    либо в ``KEY_TO_NODE``, либо (ровно один раз, сознательно) в
    ``DEFERRED_KEYS``. Незамапленный ключ — это молча потерянное право:
    человек, у которого оно было, потеряет его при переносе, и причину
    будут искать в ролях.

    ⚠️ Бриф задачи называет 31 ключ; на деле ``len(apps.hr.permissions.
    ALL_KEYS) == 30`` (проверено — см. отчёт задачи 1). Тест поэтому
    сверяется с САМИМ ``ALL_KEYS``, а не с числом 31 из брифа.
    """
    mapped = set(legacy_roles.KEY_TO_NODE)
    unmapped = legacy.ALL_KEYS - mapped - legacy_roles.DEFERRED_KEYS
    assert unmapped == set(), f"потерянные при переносе ключи: {sorted(unmapped)}"

    # DEFERRED_KEYS — не мусорная корзина: каждый его ключ обязан
    # действительно существовать в ALL_KEYS и не быть замаплен параллельно.
    assert legacy_roles.DEFERRED_KEYS <= legacy.ALL_KEYS
    assert legacy_roles.DEFERRED_KEYS.isdisjoint(mapped)
    # Решение 3 из брифа: единственное сознательное исключение — чужой ключ
    # apps.contracts.
    assert legacy_roles.DEFERRED_KEYS == frozenset(
        {legacy.CONTRACTS_ADVANCE_PAYMENT_RECORD_PAYMENT}
    )


def test_every_mapped_node_exists_in_the_registry():
    """Узел, которого нет в реестре функций, не даст прав вообще — роль
    ссылалась бы в пустоту. Сверяем с ``apps.access.registry`` (он собирает
    узлы ВСЕХ аппок через ``access_functions.py``), а не со списком в
    ``apps/hr/access_functions.py`` напрямую."""
    known = registry.paths()
    unknown = {
        node for node, _flags in legacy_roles.KEY_TO_NODE.values()
        if node not in known
    }
    assert unknown == set(), f"узлы вне реестра функций: {sorted(unknown)}"


def test_every_mapped_flag_is_a_real_depth_flag():
    """Признаки — только из ``depth.FLAGS`` (view/create/edit/delete).

    ``apps.hr.legacy_roles`` намеренно не импортирует ``apps.access.depth``
    (см. докстринг модуля — иначе завалился бы ``test_app_isolation``) и
    хранит те же значения строковыми литералами; здесь, в тестах, сверить их
    друг с другом можно и нужно напрямую."""
    allowed = set(depth.FLAGS)
    for key, (node, flags) in legacy_roles.KEY_TO_NODE.items():
        unknown = set(flags) - allowed
        assert not unknown, f"{key} -> {node}: неизвестные признаки {unknown}"


# ── Миграция 0005: роли и глубина ───────────────────────────────────────────


@pytest.mark.django_db
def test_four_roles_are_seeded_and_are_system():
    """Четыре роли заведены миграцией, ``is_system=True``: удалить их через
    API нельзя — это опора переноса."""
    _seed()
    codes = set(legacy_roles.ROLE_CODES.values())
    roles = {r.code: r for r in Role.objects.filter(code__in=codes)}
    assert set(roles) == codes
    assert all(role.is_system for role in roles.values()), (
        "не системные роли: "
        f"{[code for code, role in roles.items() if not role.is_system]}"
    )


# Числа выписаны ВРУЧНУЮ (не тем же выражением, что nodes_for_level +
# depth.legacy_level в коде) — по прочтению apps/hr/permissions.py вместе с
# готовой раскладкой apps/hr/legacy_roles.KEY_TO_NODE:
#
# * junior — в _JUNIOR только *.view-ключи -> в поддереве hr только VIEW ->
#   read (совпадает с описанием каталога: "просмотр своих данных").
# * middle — впервые появляется EDIT (EMPLOYEES_EDIT/DEPARTMENTS_EDIT/…) и
#   CREATE (DOCUMENTS_MANAGE -> FULL) -> write, delete ещё не встречается ни
#   у одного ключа этого уровня -> write (совпадает с "редактирование
#   данных").
# * senior — здесь ВПЕРВЫЕ встречаются ORG_EDIT, CALENDAR_MANAGE,
#   STAFFING_MANAGE; все три СЕГОДНЯ реально гейтят DELETE-эндпойнты в
#   apps/hr/views.py (remove_reporting_relation,
#   _delete_calendar_template, _delete_staffing_line — проверено по
#   use-сайтам, не предположено), поэтому их узлы несут признак delete уже
#   на senior. Поддерево hr получает delete -> admin. Это НЕ завышение
#   перевода: ORG_EDIT/CALENDAR_MANAGE/STAFFING_MANAGE уже были в _SENIOR у
#   портированного как данные apps/hr/permissions.py — старый пресет молча
#   нёс это с самого начала, каталог просто не афишировал это в описании
#   ("полный просмотр + создание сотрудников").
# * lead — EMPLOYEES_DELETE добавляет delete прямо на hr.employees ->
#   тоже admin (совпадает с "полный доступ ко всем HR-функциям").
EXPECTED_LEGACY_LEVEL = {
    "junior": depth.LEGACY_READ,
    "middle": depth.LEGACY_WRITE,
    "senior": depth.LEGACY_ADMIN,
    "lead": depth.LEGACY_ADMIN,
}


@pytest.mark.django_db
def test_each_role_reproduces_the_level_it_replaces():
    """ГЛАВНЫЙ тест задачи. Для каждого из четырёх уровней: собрать права
    роли, посчитать по ним модульный уровень (``depth.legacy_level`` по
    поддереву узлов модуля ``hr``) и сверить с EXPECTED_LEGACY_LEVEL,
    выписанным вручную выше. Роль, дающая МЕНЬШЕ прежнего, запрёт людей;
    дающая БОЛЬШЕ — откроет лишнее.

    Сверяет только ГЕЙТ-УРОВЕНЬ (набор признаков по узлам, спроецированный в
    read/write/admin) — область («свой отдел» у junior/middle против «вся
    компания» у senior/lead, ``PositionRole.scope_kind`` из задачи 1b) этот
    тест не трогает вовсе: она не входит ни в ``Role``, ни в
    ``RolePermission``, которые сеет задача 1, а появляется только там, где
    роль ВЫДАЮТ. Проверка области — отдельным файлом,
    ``apps/access/tests/test_position_role_scope.py``."""
    _seed()
    for level, role_code in legacy_roles.ROLE_CODES.items():
        subtree: frozenset[str] = frozenset()
        for row in RolePermission.objects.filter(role__code=role_code):
            if row.node == "hr" or row.node.startswith("hr."):
                subtree |= row.flags
        got = depth.legacy_level(subtree)
        assert got == EXPECTED_LEGACY_LEVEL[level], (
            f"{role_code}: поддерево hr = {sorted(subtree)} -> {got}, "
            f"ожидали {EXPECTED_LEGACY_LEVEL[level]}"
        )


_LEVEL_ORDER = ("junior", "middle", "senior", "lead")


@pytest.mark.django_db
def test_roles_grow_monotonically():
    """junior ⊂ middle ⊂ senior ⊂ lead по узлам и признакам — ровно так
    устроены ``LEVEL_PRESETS``, и перенос обязан это сохранить."""
    _seed()
    by_level = {
        level: {
            row.node: row.flags
            for row in RolePermission.objects.filter(
                role__code=legacy_roles.ROLE_CODES[level]
            )
        }
        for level in _LEVEL_ORDER
    }
    for lower, upper in zip(_LEVEL_ORDER, _LEVEL_ORDER[1:]):
        lower_nodes, upper_nodes = by_level[lower], by_level[upper]
        for node, flags in lower_nodes.items():
            assert node in upper_nodes, f"{upper} потерял узел {node} (был у {lower})"
            assert flags <= upper_nodes[node], (
                f"{upper}.{node} = {sorted(upper_nodes[node])} уже, чем "
                f"{lower}.{node} = {sorted(flags)}"
            )


@pytest.mark.django_db
def test_seeding_twice_changes_nothing():
    """Миграция идемпотентна: повторный прогон не плодит вторых ролей и не
    множит строки прав."""
    _seed()
    codes = set(legacy_roles.ROLE_CODES.values())
    roles_before = Role.objects.filter(code__in=codes).count()
    perms_before = RolePermission.objects.filter(role__code__in=codes).count()
    assert roles_before == 4
    assert perms_before > 0

    _seed()

    assert Role.objects.filter(code__in=codes).count() == roles_before
    assert RolePermission.objects.filter(role__code__in=codes).count() == perms_before
