"""Сторож «перенести как есть» по КАЖДОМУ ключу — фикс-раунд 1 задачи 9 блока I.

Задача 1 сверяла засеянные роли (``access/migrations/0005``) со старыми
уровнями только по АГРЕГАТУ модуля (``test_each_role_reproduces_the_level_
it_replaces`` — read/write/admin по поддереву ``hr``). Этого мало: глубина
наследуется вниз (``resolve._nearest``), и под-узел без собственной строки
получает признаки предка. Так ``hr-junior`` с ``hr.employees: view`` видел
зарплату и паспорт (``hr.employees.salary``/``.passport`` строк не имели), а
``hr-middle`` с ``hr.employees: edit`` писал идентичность в обход
подтверждения (``hr.employees.identity``) — то, чего старая матрица
``LEVEL_PRESETS`` не давала ни одному уровню. Пока старая модель стояла
«И-И», расширение было невидимо; задача 9 её сняла, и §6 её отчёта
перечислил расхождения.

Здесь — проверка ровно того, что обещал перенос: для каждого уровня и
КАЖДОГО старого ключа ``has(key)`` под засеянной ролью ⇔ ``key ∈
LEVEL_PRESETS[level]``. Считается тем же способом, что ``apps.hr.rbac.
NodeAccess.has`` для живого запроса: ключ → узел + признаки по
``legacy_roles.KEY_TO_NODE``, действующие признаки узла — ``resolve._nearest``
по строкам роли. Строки берутся из БД после ВСЕХ миграций (0005 + 0008 с
явными запретами на под-узлах), сиды прогоняются повторно как обычные
функции — тот же приём, что в ``test_hr_level_roles.py``.

Не сверяются два вида ключей: ``DEFERRED_KEYS`` (чужая аппка, узла нет —
нечем) и ``EMPLOYEES_VIEW_ALL`` — по решению 1 задачи 1 это не ПРИЗНАК, а
ОБЛАСТЬ выдачи роли (``PositionRole.scope_kind``/``RoleAssignment``:
junior/middle получают ``DEPARTMENT``, senior/lead — ``COMPANY``); в таблице
он нарочно ведёт на тот же узел и признак, что ``EMPLOYEES_VIEW``, и ни одна
ручка не спрашивает его через ``has()`` — область читает
``NodeAccess.can_read_all`` из ``permissions_for(...)["hr"]["scope"]``
(``apps/access/tests/test_position_role_scope.py``).
"""

from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest
from django.apps import apps as django_apps

from apps.access.models import RolePermission
from apps.access.services.resolve import _nearest
from apps.hr import legacy_roles
from apps.hr import permissions as legacy

_SEEDS = (
    "apps.access.migrations.0005_seed_hr_level_roles",
    "apps.access.migrations.0008_hr_role_subnode_denies",
)


def _seed() -> None:
    for name in _SEEDS:
        try:
            module = importlib.import_module(name)
        except ModuleNotFoundError:
            # На BASE (до миграции 0008) сторож обязан краснеть на ДАННЫХ,
            # а не на импорте — сеем то, что есть.
            continue
        module.seed(django_apps, SimpleNamespace())


def _rows(role_code: str) -> dict[str, frozenset[str]]:
    return {
        row.node: row.flags
        for row in RolePermission.objects.filter(role__code=role_code)
    }


#: Область, не признак — см. докстринг модуля.
SCOPE_KEYS = frozenset({legacy.EMPLOYEES_VIEW_ALL})

CHECKED_KEYS = sorted(legacy.ALL_KEYS - legacy_roles.DEFERRED_KEYS - SCOPE_KEYS)


@pytest.mark.django_db
@pytest.mark.parametrize("level", ["junior", "middle", "senior", "lead"])
def test_seeded_role_answers_every_key_exactly_as_the_old_preset(level):
    _seed()
    nodes = _rows(legacy_roles.ROLE_CODES[level])
    preset = legacy.LEVEL_PRESETS[level]

    widened, narrowed = [], []
    for key in CHECKED_KEYS:
        node, flags = legacy_roles.KEY_TO_NODE[key]
        has = frozenset(flags) <= _nearest(nodes, node)
        if has and key not in preset:
            widened.append(f"{key} (через {node}{'' if node in nodes else ' <- предок'})")
        elif not has and key in preset:
            narrowed.append(f"{key} (узел {node}, есть {sorted(_nearest(nodes, node))})")

    assert not widened, f"{level}: роль даёт БОЛЬШЕ старого пресета: {widened}"
    assert not narrowed, f"{level}: роль даёт МЕНЬШЕ старого пресета: {narrowed}"
