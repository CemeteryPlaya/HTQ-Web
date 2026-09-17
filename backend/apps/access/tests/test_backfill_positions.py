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
)
from apps.access.models import PositionRole, Role, RoleAssignment, ScopeKind
from apps.hr import legacy_roles
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


def test_scope_kind_matches_controller_decision():
    """junior/middle — DEPARTMENT (старая модель сужала список сотрудников
    до своего отдела), senior/lead — COMPANY (несли hr.employees.view.all)."""
    assert SCOPE_KIND_BY_LEVEL["junior"] == ScopeKind.DEPARTMENT
    assert SCOPE_KIND_BY_LEVEL["middle"] == ScopeKind.DEPARTMENT
    assert SCOPE_KIND_BY_LEVEL["senior"] == ScopeKind.COMPANY
    assert SCOPE_KIND_BY_LEVEL["lead"] == ScopeKind.COMPANY


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
