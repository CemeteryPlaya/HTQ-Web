"""``manage.py access_backfill_positions`` — перенос кадровых уровней в роли
должностей (блок I, задача 2).

Каждый тест здесь — одна из обязательных проверок брифа
(``.superpowers/sdd/2026-09-17-block-i-single-rbac/task-2-brief.md``).

``apps.hr`` импортируется напрямую (не через ``interface``) — это нормально
ИМЕННО в ``tests/``: ``apps/core/tests/test_app_isolation.py`` каталоги
тестов не сканирует (см. его же докстринг и ``apps/access/tests/
test_hr_level_roles.py``, который делает то же самое).
"""

from __future__ import annotations

import datetime
import importlib
from types import SimpleNamespace

import pytest
from django.apps import apps as django_apps
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.access.management.commands.access_backfill_positions import (
    ROLE_CODE_BY_LEVEL,
    SCOPE_KIND_BY_LEVEL,
    custom_role_code,
    custom_role_nodes,
)
from apps.access.models import PositionRole, Role, RoleAssignment, RolePermission, ScopeKind
from apps.access.services.resolve import _nearest
from apps.hr import legacy_roles
from apps.hr import permissions as legacy
from htqweb.tenancy.db import use_company

_seed_migration = importlib.import_module(
    "apps.access.migrations.0005_seed_hr_level_roles"
)


def _seed_roles() -> None:
    """Гарантировать, что четыре системные роли на месте — тем же приёмом,
    что ``apps/access/tests/test_hr_level_roles.py::_seed``: прогнать сид
    миграции 0005 как обычную функцию. Идемпотентно (get_or_create внутри),
    поэтому безопасно звать, даже если pytest-django уже применил все
    миграции при создании тестовой БД."""
    _seed_migration.seed(django_apps, SimpleNamespace())


def _run(**kwargs):
    call_command("access_backfill_positions", verbosity=1, **kwargs)


def _department(name: str, path: str):
    from apps.hr.models import Department

    return Department.objects.create(name=name, path=path)


def _position(title: str, department, weight: int, permissions=None):
    from apps.hr.models import Position

    return Position.objects.create(
        title=title, department=department, weight=weight, permissions=permissions,
    )


def _employee(position, department, email: str, first="Т", last="Тестов"):
    from apps.hr.models import Employee

    return Employee.objects.create(
        first_name=first, last_name=last, email=email,
        department=department, position=position,
        hire_date=datetime.date(2024, 1, 9),
    )


# ── Соответствие констант команды каноническому источнику (задача 1) ───────


def test_role_codes_match_legacy_source():
    """``ROLE_CODE_BY_LEVEL`` заморожен ИЗ ``apps.hr.legacy_roles.ROLE_CODES``,
    а не изобретён — сверяем оба словаря напрямую (разрешено только в
    tests/, см. докстринг модуля)."""
    assert ROLE_CODE_BY_LEVEL == legacy_roles.ROLE_CODES


def test_scope_kinds_match_legacy_source():
    """``apps.hr.legacy_roles.SCOPE_KINDS`` (его читает ``seed_hr_demo``,
    задача 11) обязан совпадать с правилом переноса — иначе стенд и бой
    получат разные области для одного и того же уровня."""
    assert SCOPE_KIND_BY_LEVEL == legacy_roles.SCOPE_KINDS


def test_scope_kind_matches_controller_decision():
    """junior/middle — DEPARTMENT (старая модель сужала список сотрудников
    до своего отдела), senior/lead — COMPANY (несли hr.employees.view.all)."""
    assert SCOPE_KIND_BY_LEVEL["junior"] == ScopeKind.DEPARTMENT
    assert SCOPE_KIND_BY_LEVEL["middle"] == ScopeKind.DEPARTMENT
    assert SCOPE_KIND_BY_LEVEL["senior"] == ScopeKind.COMPANY
    assert SCOPE_KIND_BY_LEVEL["lead"] == ScopeKind.COMPANY


def test_list_positions_hr_levels_has_no_silent_truncation_limit():
    """Раунд правок 1 (Important 2): функция раньше резала список должностей
    ``[:limit]`` (умолчание 5000) — компания с большим числом должностей
    получила бы честную на вид, но неполную сводку. Параметр убран вовсе, а
    не просто увеличен: любой лимит здесь снова мог бы стать молчаливым."""
    import inspect

    from apps.hr import interface as hr

    params = inspect.signature(hr.list_positions_hr_levels).parameters
    assert "limit" not in params


# ── Step 1: обязательные проверки брифа ─────────────────────────────────────


def test_explicit_hr_level_gets_the_matching_role(company_schema, capsys):
    """Должность с permissions={"hr_level": "senior"} получает PositionRole
    на hr-senior в своей компании — даже без единого держателя."""
    _seed_roles()
    slug = company_schema["slug"]
    with use_company(slug):
        dep = _department("Руководство", "upr")
        position = _position("Директор по персоналу", dep, weight=10,
                             permissions={"hr_level": "senior"})

    _run(company=slug)

    role = PositionRole.objects.get(company_slug=slug, position_id=position.id)
    assert role.role.code == "hr-senior"
    assert role.scope_kind == ScopeKind.COMPANY


def test_heuristic_level_gets_role_with_department_scope(company_schema, capsys):
    """Должность БЕЗ permissions получает роль по угадыванию
    (classify_hr_level) через держателя — junior/middle => DEPARTMENT."""
    _seed_roles()
    slug = company_schema["slug"]
    with use_company(slug):
        dep = _department("Отдел кадров", "hr-dep")
        position = _position("HR-специалист", dep, weight=20)
        _employee(position, dep, "specialist@htq.test")

    _run(company=slug)

    role = PositionRole.objects.get(company_slug=slug, position_id=position.id)
    # "специалист" -> middle marker в classify_hr_level.
    assert role.role.code == "hr-middle"
    assert role.scope_kind == ScopeKind.DEPARTMENT


def test_divergent_holder_levels_are_flagged_but_do_not_change_the_rule(
        company_schema, capsys):
    """Раунд правок 1 (Important 1): два держателя ОДНОЙ должности дают
    РАЗНЫЙ уровень (``Employee.department`` независим от ``Position.
    department``, а эвристика смотрит на отдел держателя) — расхождение
    обязано попасть в сводку отдельной категорией, а роль ставится по
    прежнему правилу (первый держатель по id), которое НЕ меняется."""
    _seed_roles()
    slug = company_schema["slug"]
    with use_company(slug):
        # Заголовок должности НЕ несёт HR-маркеров сам по себе — только
        # "специалист" (middle-маркер), поэтому is_hr решает ИМЕННО отдел
        # держателя, а не название должности.
        dep_hr = _department("Отдел кадров", "hr-div")       # "кадр" -> is_hr
        dep_sales = _department("Продажи", "sales-div")       # без HR-маркеров
        position = _position("Специалист", dep_hr, weight=25)
        # Первый по id — держатель из HR-отдела -> classify_hr_level="middle".
        _employee(position, dep_hr, "holder1@htq.test", first="А", last="Первый")
        # Второй по id — держатель из отдела без HR-маркеров -> level=None.
        _employee(position, dep_sales, "holder2@htq.test", first="Б", last="Второй")

    _run(company=slug)

    # Правило выбора роли не изменилось: взят первый держатель по id -> middle.
    role = PositionRole.objects.get(company_slug=slug, position_id=position.id)
    assert role.role.code == "hr-middle"

    out = capsys.readouterr().out
    assert "расхождение по держателям" in out
    assert f"#{position.id}" in out
    assert "middle" in out
    assert "нет уровня" in out
    assert "расхождений по держателям 1" in out


def test_first_holder_without_level_skips_the_position_and_prints_divergence(
        company_schema, capsys):
    """Блок I.2, R7: зеркало предыдущего теста — ПЕРВЫЙ держатель по id
    уровня не даёт, второй даёт ``middle``. Правило то же (первый по id), так
    что должность пропущена, а не повышена по второму держателю; и именно
    этот случай сводка обязана показать — иначе держатель, у которого права
    были, молча остаётся без роли."""
    _seed_roles()
    slug = company_schema["slug"]
    with use_company(slug):
        dep_hr = _department("Отдел кадров", "hr-div-rev")    # "кадр" -> is_hr
        dep_sales = _department("Продажи", "sales-div-rev")    # без HR-маркеров
        position = _position("Специалист", dep_hr, weight=26)
        # Первый по id — держатель из отдела без HR-маркеров -> level=None.
        _employee(position, dep_sales, "rev1@htq.test", first="А", last="Первый")
        # Второй по id — держатель из HR-отдела -> classify_hr_level="middle".
        _employee(position, dep_hr, "rev2@htq.test", first="Б", last="Второй")

    _run(company=slug)

    assert not PositionRole.objects.filter(
        company_slug=slug, position_id=position.id,
    ).exists()
    out = capsys.readouterr().out
    assert "расхождение по держателям" in out
    assert f"#{position.id}" in out
    assert "middle, нет уровня" in out
    assert "для роли взят нет уровня (должность пропущена)" in out
    assert "пропущено 1" in out
    assert "расхождений по держателям 1" in out


def test_position_with_no_signal_gets_no_role(company_schema, capsys):
    """Должность без permissions и без держателя, по которому угадать —
    роли не получает. Перенос не выдумывает прав."""
    _seed_roles()
    slug = company_schema["slug"]
    with use_company(slug):
        dep = _department("Продажи", "sales")
        position = _position("Специалист по продажам", dep, weight=30)
        # Ни одного Employee на эту должность.

    _run(company=slug)

    assert not PositionRole.objects.filter(
        company_slug=slug, position_id=position.id,
    ).exists()
    out = capsys.readouterr().out
    assert "пропущено 1" in out


def test_second_run_does_not_duplicate(company_schema, capsys):
    """Идемпотентность: второй прогон не создаёт вторых связей."""
    _seed_roles()
    slug = company_schema["slug"]
    with use_company(slug):
        dep = _department("Руководство", "upr2")
        position = _position("Директор по персоналу", dep, weight=11,
                             permissions={"hr_level": "senior"})

    _run(company=slug)
    first_count = PositionRole.objects.filter(
        company_slug=slug, position_id=position.id).count()
    assert first_count == 1

    _run(company=slug)
    second_count = PositionRole.objects.filter(
        company_slug=slug, position_id=position.id).count()
    assert second_count == 1

    out = capsys.readouterr().out
    assert "создано сейчас 0" in out
    assert "уже было верно 1" in out


def test_dry_run_writes_nothing(company_schema, capsys):
    """--dry-run не пишет НИЧЕГО и печатает то же, что записал бы."""
    _seed_roles()
    slug = company_schema["slug"]
    with use_company(slug):
        dep = _department("Руководство", "upr3")
        position = _position("Директор по персоналу", dep, weight=12,
                             permissions={"hr_level": "senior"})

    _run(company=slug, dry_run=True)
    dry_out = capsys.readouterr().out

    assert not PositionRole.objects.filter(
        company_slug=slug, position_id=position.id).exists()
    assert "создано сейчас 1" in dry_out
    assert "уже было верно 0" in dry_out

    _run(company=slug)
    real_out = capsys.readouterr().out
    assert "создано сейчас 1" in real_out
    assert "уже было верно 0" in real_out
    assert PositionRole.objects.filter(
        company_slug=slug, position_id=position.id, role__code="hr-senior",
    ).exists()


def test_companies_are_isolated(two_company_schemas, capsys):
    """Должности компании A не получают ролей в компании B."""
    _seed_roles()
    slug_a, slug_b = two_company_schemas
    with use_company(slug_a):
        dep_a = _department("Руководство А", "upr-a")
        position_a = _position("Директор по персоналу", dep_a, weight=13,
                               permissions={"hr_level": "senior"})
    with use_company(slug_b):
        dep_b = _department("Руководство Б", "upr-b")
        position_b = _position("Директор по персоналу", dep_b, weight=13,
                               permissions={"hr_level": "junior"})

    _run(company=slug_a)

    assert PositionRole.objects.filter(
        company_slug=slug_a, position_id=position_a.id, role__code="hr-senior",
    ).exists()
    # Компания B вообще не обрабатывалась — в ней нет ни одной строки.
    assert not PositionRole.objects.filter(company_slug=slug_b).exists()

    # Убедиться, что запуск для B не тронул A и завёл свою собственную связь,
    # даже если position_id совпадает между схемами.
    _run(company=slug_b)
    assert PositionRole.objects.filter(
        company_slug=slug_b, position_id=position_b.id, role__code="hr-junior",
    ).exists()
    assert PositionRole.objects.filter(
        company_slug=slug_a, position_id=position_a.id, role__code="hr-senior",
    ).count() == 1


def test_existing_different_role_is_not_overwritten(company_schema, capsys):
    """Существующая связь должности с ДРУГОЙ ролью не затирается — команда
    сообщает и не трогает (кадровик мог назначить роль раньше)."""
    _seed_roles()
    slug = company_schema["slug"]
    lead_role = Role.objects.get(code="hr-lead")
    with use_company(slug):
        dep = _department("Отдел кадров", "hr-dep2")
        position = _position("HR-специалист", dep, weight=21)
        _employee(position, dep, "specialist2@htq.test")

    # Кадровик уже вручную назначил hr-lead этой должности.
    PositionRole.objects.create(
        company_slug=slug, position_id=position.id, role=lead_role,
        scope_kind=ScopeKind.COMPANY,
    )

    _run(company=slug)

    rows = list(PositionRole.objects.filter(company_slug=slug, position_id=position.id))
    assert len(rows) == 1
    assert rows[0].role.code == "hr-lead"
    assert rows[0].scope_kind == ScopeKind.COMPANY

    out = capsys.readouterr().out
    assert "конфликт" in out
    assert f"#{position.id}" in out
    assert "hr-lead" in out
    assert "hr-middle" in out


def test_summary_reports_totals_and_reasons(company_schema, capsys):
    """Сводка: сколько должностей, сколько получили роль, сколько пропущено
    и почему."""
    _seed_roles()
    slug = company_schema["slug"]
    with use_company(slug):
        dep = _department("Руководство", "upr4")
        _position("Директор по персоналу", dep, weight=14,
                  permissions={"hr_level": "senior"})
        _position("Специалист по продажам", dep, weight=15)  # без сигнала

    _run(company=slug)

    out = capsys.readouterr().out
    assert "должностей всего 2" in out
    assert "роль назначена 1" in out
    assert "пропущено 1" in out
    assert "без сигнала об уровне" in out


def test_command_does_not_touch_role_assignment(company_schema, capsys):
    """Команда про должности — RoleAssignment (персональные назначения) она
    не трогает вовсе."""
    _seed_roles()
    slug = company_schema["slug"]
    with use_company(slug):
        dep = _department("Руководство", "upr5")
        _position("Директор по персоналу", dep, weight=16,
                  permissions={"hr_level": "senior"})

    _run(company=slug)

    assert RoleAssignment.objects.filter(company_slug=slug).count() == 0


def test_unknown_company_is_refused(db):
    with pytest.raises(CommandError, match="не найдена"):
        _run(company="t-no-such-company")


def test_company_without_schema_is_refused(db):
    from apps.companies.models import Company, CompanyKind

    Company.objects.create(slug="t-orphan-backfill", name="Сирота",
                           kind=CompanyKind.HOLDING)
    with pytest.raises(CommandError, match="схем"):
        _run(company="t-orphan-backfill")


def test_no_company_flag_processes_all_active_companies(two_company_schemas, capsys):
    """Без --company обходятся все действующие компании
    (apps.companies.interface.active_company_slugs)."""
    _seed_roles()
    slug_a, slug_b = two_company_schemas
    with use_company(slug_a):
        dep_a = _department("Руководство А2", "upr-a2")
        position_a = _position("Директор по персоналу", dep_a, weight=17,
                               permissions={"hr_level": "senior"})
    with use_company(slug_b):
        dep_b = _department("Руководство Б2", "upr-b2")
        position_b = _position("Директор по персоналу", dep_b, weight=17,
                               permissions={"hr_level": "junior"})

    _run()

    assert PositionRole.objects.filter(
        company_slug=slug_a, position_id=position_a.id, role__code="hr-senior",
    ).exists()
    assert PositionRole.objects.filter(
        company_slug=slug_b, position_id=position_b.id, role__code="hr-junior",
    ).exists()


# ── Финальная волна блока I, рулинг K: явный список ключей должности ──────
#
# Старый резолвер (``1f69716:backend/apps/hr/access.py::resolve_hr_access``)
# знал ТРИ источника: непустой ``Position.permissions["permissions"]``
# ЗАМЕНЯЛ пресет уровня целиком. Перенос, смотревший только на уровень,
# молча терял таких держателей (без уровня — ни одной роли) или расширял их
# (уровень + суженный список — полный пресет). Первый тест ниже — зонд
# финального ревьюера (``final-review.md``, F1), повторённый как тест.

_SEED_0008 = importlib.import_module("apps.access.migrations.0008_hr_role_subnode_denies")

#: Под-узлы ``hr.employees``, у которых есть свой старый ключ: именная роль с
#: ``hr.employees`` без их ключей обязана нести на них явный запрет.
_EMPLOYEE_SUBNODES = (
    "hr.employees.family", "hr.employees.identity", "hr.employees.passport",
    "hr.employees.salary", "hr.employees.transfer",
)


def _seed_all_roles() -> None:
    _seed_roles()
    _SEED_0008.seed(django_apps, SimpleNamespace())


def _role_rows(role) -> dict[str, frozenset[str]]:
    return {row.node: row.flags for row in RolePermission.objects.filter(role=role)}


def test_probe_f1_list_without_level_gets_a_custom_role(company_schema, capsys):
    """Зонд F1: «Бухгалтер» без ``hr_level`` и без HR-маркеров, но с явным
    списком ``[hr.employees.view, hr.documents.view]``. Старая модель пускала
    держателя (``has_access=True``, ``has("hr.employees.view")``); перенос до
    рулинга K — «без сигнала об уровне», ``PositionRole`` пуст."""
    _seed_all_roles()
    slug = company_schema["slug"]
    keys = [legacy.EMPLOYEES_VIEW, legacy.DOCUMENTS_VIEW]
    with use_company(slug):
        dep = _department("Бухгалтерия", "buh")
        position = _position("Бухгалтер", dep, weight=40,
                             permissions={"hr_level": None, "permissions": keys})
        _employee(position, dep, "buh@htq.test")

    _run(company=slug)

    link = PositionRole.objects.get(company_slug=slug, position_id=position.id)
    assert link.role.code == custom_role_code(slug, position.id)
    assert link.role.is_system is False
    assert link.scope_kind == ScopeKind.DEPARTMENT
    # Блок I.2, R2: именная роль принадлежит компании, чья должность её
    # породила — соседям её не видно в общем каталоге.
    assert link.role.company_slug == slug
    assert _role_rows(link.role) == {
        "hr.employees": frozenset({"view"}),
        "hr.documents": frozenset({"view"}),
        **{node: frozenset() for node in _EMPLOYEE_SUBNODES},
    }
    out = capsys.readouterr().out
    assert "явный список ключей" in out
    assert f"#{position.id}" in out
    assert "hr.documents.view, hr.employees.view" in out
    assert "hr.employees.salary=запрет" in out
    assert "область: department" in out
    assert "без сигнала об уровне" not in out


def test_level_with_narrowed_list_gets_custom_role_not_the_level_role(
        company_schema, capsys):
    """Уровень senior + список, суженный руками (сняты финансы): старая
    модель давала ровно список, а не пресет. Роль уровня была бы
    расширением — должность получает именную роль."""
    _seed_all_roles()
    slug = company_schema["slug"]
    keys = sorted(legacy.LEVEL_PRESETS["senior"]
                  - {legacy.CARD_FINANCIAL_VIEW, legacy.CARD_FINANCIAL_EDIT})
    with use_company(slug):
        dep = _department("Отдел кадров", "hr-narrow")
        position = _position("HR-специалист", dep, weight=41,
                             permissions={"hr_level": "senior", "permissions": keys})
        _employee(position, dep, "narrow@htq.test")

    _run(company=slug)

    links = list(PositionRole.objects.filter(company_slug=slug, position_id=position.id))
    assert [link.role.code for link in links] == [custom_role_code(slug, position.id)]
    rows = _role_rows(links[0].role)
    assert rows["hr.employees.salary"] == frozenset()
    assert rows["hr.employees.passport"] == frozenset({"view", "edit"})
    # view.all в списке — вся компания, как старый can_read_all.
    assert links[0].scope_kind == ScopeKind.COMPANY


@pytest.mark.parametrize(("keys", "scope"), [
    (["hr.employees.view", "hr.employees.view.all"], ScopeKind.COMPANY),
    (["hr.employees.view", "hr.reports.view"], ScopeKind.DEPARTMENT),
])
def test_custom_role_scope_follows_view_all(company_schema, keys, scope):
    _seed_all_roles()
    slug = company_schema["slug"]
    with use_company(slug):
        dep = _department("Склад", f"sklad-{scope}")
        position = _position("Кладовщик", dep, weight=42,
                             permissions={"permissions": keys})

    _run(company=slug)

    link = PositionRole.objects.get(company_slug=slug, position_id=position.id)
    assert link.role.code == custom_role_code(slug, position.id)
    assert link.scope_kind == scope


def test_custom_role_second_run_creates_nothing(company_schema, capsys):
    _seed_all_roles()
    slug = company_schema["slug"]
    with use_company(slug):
        dep = _department("Бухгалтерия", "buh-rerun")
        position = _position("Бухгалтер", dep, weight=43, permissions={
            "permissions": [legacy.EMPLOYEES_VIEW, legacy.DOCUMENTS_VIEW]})

    _run(company=slug)
    capsys.readouterr()
    _run(company=slug)
    out = capsys.readouterr().out

    assert "создано сейчас 0" in out
    assert "уже было верно 1" in out
    assert "роль уже есть" in out
    assert Role.objects.filter(code=custom_role_code(slug, position.id)).count() == 1
    assert PositionRole.objects.filter(
        company_slug=slug, position_id=position.id).count() == 1


def test_custom_role_dry_run_prints_the_line_and_writes_nothing(company_schema, capsys):
    _seed_all_roles()
    slug = company_schema["slug"]
    with use_company(slug):
        dep = _department("Бухгалтерия", "buh-dry")
        position = _position("Бухгалтер", dep, weight=44, permissions={
            "permissions": [legacy.EMPLOYEES_VIEW]})

    _run(company=slug, dry_run=True)
    out = capsys.readouterr().out

    assert "[dry-run]" in out
    assert custom_role_code(slug, position.id) in out
    assert "создано сейчас 1" in out
    assert not Role.objects.filter(code=custom_role_code(slug, position.id)).exists()
    assert not PositionRole.objects.filter(company_slug=slug).exists()


def test_list_equal_to_a_level_preset_gets_that_level_role(company_schema, capsys):
    """Форма должности сохраняла список = пресет выбранного уровня (+ ключ
    contracts галочкой). Именная роль вышла бы копией роли уровня — перенос
    выдаёт саму роль уровня, каталог не зарастает копиями.

    Блок I.2, R7: ``hr_level`` должности — НЕ тот уровень, чей пресет лежит в
    списке (junior против пресета middle). Пока они совпадали, тест был
    зелёным и с выключенной обработкой списка вовсе (``if
    position["explicit_list"]`` → ложь: роль бралась по ``hr_level``, и это
    была та же ``hr-middle``) — то есть ветку «список = пресет» он не
    отличал. Теперь три исхода различимы: ветка работает — ``hr-middle``
    (права давал список, а он = пресет middle); ветка сравнения выключена —
    именная ``hr-custom-…``; список проигнорирован — ``hr-junior``."""
    _seed_all_roles()
    slug = company_schema["slug"]
    keys = sorted(legacy.LEVEL_PRESETS["middle"]
                  | {legacy.CONTRACTS_ADVANCE_PAYMENT_RECORD_PAYMENT})
    with use_company(slug):
        dep = _department("Отдел кадров", "hr-preset")
        position = _position("HR-специалист", dep, weight=45,
                             permissions={"hr_level": "junior", "permissions": keys})

    _run(company=slug)

    links = list(PositionRole.objects.filter(company_slug=slug, position_id=position.id))
    assert [link.role.code for link in links] == ["hr-middle"]
    assert links[0].scope_kind == ScopeKind.DEPARTMENT
    assert not Role.objects.filter(code=custom_role_code(slug, position.id)).exists()
    assert not Role.objects.filter(code__startswith="hr-custom-").exists()


def test_list_equal_to_a_preset_but_wider_scope_is_not_that_level_role(company_schema, capsys):
    """Список = пресет middle + ``hr.employees.view.all`` (блок I.2, B5).

    ``view.all`` лежит на том же узле ``hr.employees`` с признаком view, что
    и ``hr.employees.view`` пресета middle, — узлы роли совпадают с
    ``hr-middle`` дословно. Различает их только ОБЛАСТЬ: старая модель по
    ``view.all`` давала всю компанию, а ``hr-middle`` выдаётся с областью
    отдела. Роль уровня сузила бы доступ — должность получает именную роль с
    областью компании. Без сверки области (``SCOPE_KIND_BY_LEVEL[level] ==
    scope_kind``) выдавалась бы ``hr-middle`` на отдел."""
    _seed_all_roles()
    slug = company_schema["slug"]
    keys = sorted(legacy.LEVEL_PRESETS["middle"] | {legacy.EMPLOYEES_VIEW_ALL})
    assert legacy.EMPLOYEES_VIEW_ALL not in legacy.LEVEL_PRESETS["middle"]
    with use_company(slug):
        dep = _department("Отдел кадров", "hr-wide")
        position = _position("HR-специалист", dep, weight=46,
                             permissions={"hr_level": "middle", "permissions": keys})

    _run(company=slug)

    links = list(PositionRole.objects.filter(company_slug=slug, position_id=position.id))
    assert [link.role.code for link in links] == [custom_role_code(slug, position.id)]
    assert links[0].scope_kind == ScopeKind.COMPANY
    # Узлы — ровно как у hr-middle: различие только в области.
    assert _role_rows(links[0].role) == _role_rows(Role.objects.get(code="hr-middle"))


def test_list_without_hr_keys_gets_no_role_and_is_reported(company_schema, capsys):
    """Только ключ contracts: кадровых прав список не давал (а заменял
    пресет уровня) — роли нет, строка в сводке."""
    _seed_all_roles()
    slug = company_schema["slug"]
    with use_company(slug):
        dep = _department("Бухгалтерия", "buh-contracts")
        position = _position("Бухгалтер", dep, weight=46, permissions={
            "hr_level": "senior",
            "permissions": [legacy.CONTRACTS_ADVANCE_PAYMENT_RECORD_PAYMENT]})

    _run(company=slug)

    assert not PositionRole.objects.filter(
        company_slug=slug, position_id=position.id).exists()
    out = capsys.readouterr().out
    assert "явный список без кадровых ключей" in out
    assert f"#{position.id}" in out


def test_custom_role_codes_do_not_collide_across_companies(two_company_schemas):
    """Каталог ролей общий, id должностей в схемах свои: одна и та же
    «должность 9001» в двух компаниях — две разные именные роли."""
    from apps.hr.models import Position

    _seed_all_roles()
    slug_a, slug_b = two_company_schemas
    for slug, keys in ((slug_a, [legacy.EMPLOYEES_VIEW]),
                       (slug_b, [legacy.DOCUMENTS_VIEW])):
        with use_company(slug):
            dep = _department("Бухгалтерия", f"buh-{slug}")
            Position.objects.create(id=9001, title="Бухгалтер", department=dep,
                                    weight=47, permissions={"permissions": keys})

    _run()

    role_a = PositionRole.objects.get(company_slug=slug_a, position_id=9001).role
    role_b = PositionRole.objects.get(company_slug=slug_b, position_id=9001).role
    assert role_a.id != role_b.id
    assert "hr.employees" in _role_rows(role_a)
    assert set(_role_rows(role_b)) == {"hr.documents"}
    # Блок I.2, R2: каждая именная роль несёт СВОЮ компанию, а не общий каталог.
    assert role_a.company_slug == slug_a
    assert role_b.company_slug == slug_b


@pytest.mark.django_db
@pytest.mark.parametrize("level", ["junior", "middle", "senior", "lead"])
def test_custom_nodes_of_each_preset_equal_the_level_role(level):
    """Правило именной роли, применённое к пресету уровня, даёт ДОСЛОВНО
    строки засеянной роли уровня (0005 + явные запреты 0008) — то есть
    правило запретов то же, и замена «список = пресет → роль уровня» точна."""
    _seed_all_roles()
    nodes, deferred = custom_role_nodes(legacy.LEVEL_PRESETS[level], legacy_roles.KEY_TO_NODE)
    assert deferred == []
    role = Role.objects.get(code=legacy_roles.ROLE_CODES[level])
    assert nodes == _role_rows(role)


@pytest.mark.parametrize("key", sorted(legacy.ALL_KEYS - legacy_roles.DEFERRED_KEYS))
def test_single_key_custom_role_grants_only_that_key(key):
    """Точность по ключу: роль из одного ключа отвечает «да» только на него
    и на ключи ТОГО ЖЕ узла, чьи признаки он покрывает (складывание ключей в
    узел — свойство модели узлов, у ролей уровней то же). Ключ под-узла и
    ключ предка — «нет»: запрет на под-узле и отсутствие строки у предка."""
    nodes, _deferred = custom_role_nodes([key], legacy_roles.KEY_TO_NODE)
    own_node, own_flags = legacy_roles.KEY_TO_NODE[key]
    for other, (node, flags) in legacy_roles.KEY_TO_NODE.items():
        has = frozenset(flags) <= _nearest(nodes, node)
        expected = other == key or (node == own_node and set(flags) <= set(own_flags))
        assert has == expected, (key, other)


def test_deferred_keys_are_left_out_of_the_role():
    nodes, deferred = custom_role_nodes(
        [legacy.EMPLOYEES_VIEW, legacy.CONTRACTS_ADVANCE_PAYMENT_RECORD_PAYMENT],
        legacy_roles.KEY_TO_NODE,
    )
    assert deferred == [legacy.CONTRACTS_ADVANCE_PAYMENT_RECORD_PAYMENT]
    assert nodes["hr.employees"] == frozenset({"view"})
