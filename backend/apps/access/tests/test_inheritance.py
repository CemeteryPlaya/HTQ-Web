"""Задача 5 блока C: наследование прав от вышестоящей компании (roadmap §5.C).

Ядро блока: должность вышестоящей компании, помеченная обслуживающей дочерние
компании (``Position.serves_subsidiaries``), несёт свои роли — как они
назначены В ДОМАШНЕЙ для неё компании — во все компании ниже по дереву
владения.

Схемы компаний здесь НАСТОЯЩИЕ (``two_company_schemas`` из корневого
``conftest.py``), а не заглушки: кадровая карточка кладётся строго в СВОЮ
схему через ``use_company``, иначе тест доказывал бы не обход чужой схемы
модулем ``inheritance.py``, а случайное совпадение с схемой по умолчанию.
"""

from __future__ import annotations

import datetime
import logging

import pytest
from django.db import connection, transaction

from apps.access.models import PositionRole, Role, RoleAssignment, ScopeKind
from apps.access.services import inheritance, resolve
from apps.companies.models import Company, CompanyKind, CompanyModule, CompanyStatus
from htqweb.tenancy.db import use_company


def _link(child_slug: str, parent_slug: str) -> None:
    """Завести родство между двумя уже существующими компаниями."""
    child = Company.objects.get(slug=child_slug)
    child.parent = Company.objects.get(slug=parent_slug)
    child.save(update_fields=["parent"])


def _grant_serving_position(company_slug: str, user, role: Role, *, weight: int,
                            serves: bool = True):
    """Кадровая карточка ``user`` В СХЕМЕ ``company_slug`` + роль её должности.

    Всё создаётся ВНУТРИ ``use_company``: должность и сотрудник обязаны лечь
    в физическую схему компании, а не в схему по умолчанию, иначе тест не
    отличит «обошли чужую схему» от «совпали с default».
    """
    from apps.hr.models import Department, Employee, Position

    with use_company(company_slug):
        dep = Department.objects.create(name=f"Отдел-{weight}", path=f"root-{weight}")
        pos = Position.objects.create(
            title=f"Должность-{weight}", department=dep, weight=weight,
            serves_subsidiaries=serves,
        )
        Employee.objects.create(
            first_name="Имя", last_name="Фамилия", email=f"e-{weight}@htq.test",
            department=dep, position=pos,
            hire_date=datetime.date(2024, 1, 9), user_id=user.id,
        )
        PositionRole.objects.create(
            company_slug=company_slug, position_id=pos.id, role=role)
    return pos


# ── 1. Обслуживающая должность несёт роли вниз ─────────────────────────────


@pytest.mark.django_db(transaction=True)
def test_serving_holding_position_grants_its_home_roles_in_subsidiary(
        user, two_company_schemas):
    holding, subsidiary = two_company_schemas
    _link(subsidiary, holding)

    home_role = Role.objects.create(code="r-home", title="Роль в холдинге")
    foreign_role = Role.objects.create(code="r-foreign", title="Не отсюда")

    pos = _grant_serving_position(holding, user, home_role, weight=1)
    # Та же должность (тот же position_id), но роль назначена НЕ в холдинге —
    # такая роль ехать не должна: набор ролей у должности свой в каждой
    # компании, и ключ выборки — company_slug ДОМАШНЕЙ компании, а не голый id.
    PositionRole.objects.create(
        company_slug=subsidiary, position_id=pos.id, role=foreign_role)

    scopes = inheritance.inherited_role_scopes(user.id, subsidiary)
    assert scopes == {home_role.id: (ScopeKind.COMPANY, None)}


@pytest.mark.django_db(transaction=True)
def test_non_serving_position_grants_nothing_downward(user, two_company_schemas):
    holding, subsidiary = two_company_schemas
    _link(subsidiary, holding)

    role = Role.objects.create(code="r-not-served", title="Роль")
    _grant_serving_position(holding, user, role, weight=1, serves=False)

    assert inheritance.inherited_role_scopes(user.id, subsidiary) == {}


# ── 2. Направление обхода — только вверх ───────────────────────────────────


@pytest.mark.django_db(transaction=True)
def test_subsidiary_employee_does_not_inherit_upward(user, two_company_schemas):
    """Держатель обслуживающей должности в ДО не поднимает права в холдинг."""
    top, subsidiary = two_company_schemas
    _link(subsidiary, top)

    role = Role.objects.create(code="r-below", title="Роль ниже")
    _grant_serving_position(subsidiary, user, role, weight=1)

    # top — вершина дерева, предков у неё нет вовсе; карточка ЖИВЁТ в
    # subsidiary (ниже), но спрашиваем наследование ДЛЯ top — обход не должен
    # найти вообще ничего, потому что идёт вверх, а не вниз.
    assert inheritance.ancestors_of(top) == []
    assert inheritance.inherited_role_scopes(user.id, top) == {}


@pytest.mark.django_db(transaction=True)
def test_sibling_branch_outside_the_subtree_gets_nothing(user, two_company_schemas):
    """Компания вне поддерева (без родства вовсе) ничего не получает."""
    a, b = two_company_schemas  # родство НЕ заводим — просто две компании

    role = Role.objects.create(code="r-sibling", title="Роль соседа")
    _grant_serving_position(a, user, role, weight=1)

    assert inheritance.inherited_role_scopes(user.id, b) == {}


# ── 3. Объединение с собственными правами ──────────────────────────────────


@pytest.mark.django_db(transaction=True)
def test_inherited_roles_combine_with_personal_rights_without_narrowing(
        user, two_company_schemas):
    holding, subsidiary = two_company_schemas
    _link(subsidiary, holding)

    inherited_role = Role.objects.create(code="r-inh", title="Наследуемая")
    personal_role = Role.objects.create(code="r-own", title="Личная")
    _grant_serving_position(holding, user, inherited_role, weight=1)

    RoleAssignment.objects.create(
        company_slug=subsidiary, user_id=user.id, role=personal_role,
        scope_kind=ScopeKind.DEPARTMENT, scope_id=5)
    # Личное назначение НА ТУ ЖЕ роль, что уже пришла наследованием —
    # заведомо более узкой областью. Оно не должно суметь её сузить
    # (``_SCOPE_WIDTH``, и наследование добавляется до личных назначений).
    RoleAssignment.objects.create(
        company_slug=subsidiary, user_id=user.id, role=inherited_role,
        scope_kind=ScopeKind.SITE, scope_id=1)

    scopes = resolve.resolve_for(user, subsidiary).scopes
    assert scopes[inherited_role.id] == (ScopeKind.COMPANY, None)
    assert scopes[personal_role.id] == (ScopeKind.DEPARTMENT, 5)


# ── 4. Предки не взаимоисключающи (решение 7) ──────────────────────────────


@pytest.mark.django_db(transaction=True)
def test_serving_positions_in_two_ancestors_both_grant_their_roles(
        user, two_company_schemas):
    grandparent, parent = two_company_schemas
    _link(parent, grandparent)
    bottom = Company.objects.create(
        slug="t-fixture-inh-bottom", name="Нижний уровень", kind=CompanyKind.SERVICE,
        parent=Company.objects.get(slug=parent))

    role_grandparent = Role.objects.create(code="r-gp", title="Роль деда")
    role_parent = Role.objects.create(code="r-p", title="Роль родителя")
    _grant_serving_position(grandparent, user, role_grandparent, weight=1)
    _grant_serving_position(parent, user, role_parent, weight=2)

    scopes = inheritance.inherited_role_scopes(user.id, bottom.slug)
    assert scopes == {
        role_grandparent.id: (ScopeKind.COMPANY, None),
        role_parent.id: (ScopeKind.COMPANY, None),
    }


# ── 5. Архивный предок не раздаёт, но обход идёт дальше вверх ─────────────


@pytest.mark.django_db(transaction=True)
def test_archived_ancestor_grants_nothing_but_walk_continues_above_it(
        user, two_company_schemas):
    top, archived_middle = two_company_schemas
    _link(archived_middle, top)
    bottom = Company.objects.create(
        slug="t-fixture-inh-archived-bottom", name="Ниже архивного",
        kind=CompanyKind.SERVICE, parent=Company.objects.get(slug=archived_middle))
    Company.objects.filter(slug=archived_middle).update(status=CompanyStatus.ARCHIVED)

    role_top = Role.objects.create(code="r-top-live", title="Роль живого предка")
    role_archived = Role.objects.create(code="r-archived", title="Роль архивного")
    _grant_serving_position(top, user, role_top, weight=1)
    _grant_serving_position(archived_middle, user, role_archived, weight=2)

    scopes = inheritance.inherited_role_scopes(user.id, bottom.slug)
    assert scopes == {role_top.id: (ScopeKind.COMPANY, None)}


# ── 6. Область наследованной роли ──────────────────────────────────────────


@pytest.mark.django_db(transaction=True)
def test_inherited_role_scope_is_company(user, two_company_schemas):
    holding, subsidiary = two_company_schemas
    _link(subsidiary, holding)

    role = Role.objects.create(code="r-scope-check", title="Роль")
    _grant_serving_position(holding, user, role, weight=1)

    kind, scope_id = inheritance.inherited_role_scopes(user.id, subsidiary)[role.id]
    assert kind == ScopeKind.COMPANY
    assert scope_id is None


# ── 7. Цикл в дереве владения не вешает разрешение ─────────────────────────


@pytest.mark.django_db
def test_cycle_in_ownership_tree_does_not_hang(user):
    """Цикл заводится мимо приложения — прямым UPDATE, минуя валидацию."""
    a = Company.objects.create(slug="t-fixture-inh-cycle-a", name="A",
                               kind=CompanyKind.SERVICE)
    b = Company.objects.create(slug="t-fixture-inh-cycle-b", name="B",
                               kind=CompanyKind.SERVICE, parent=a)
    Company.objects.filter(pk=a.pk).update(parent=b)

    ancestors = inheritance.ancestors_of("t-fixture-inh-cycle-b")
    assert "t-fixture-inh-cycle-b" not in ancestors
    assert len(ancestors) == len(set(ancestors))

    # Само разрешение прав обязано ЗАВЕРШИТЬСЯ (а не зависнуть) и не найти
    # ролей — ни один из двух узлов цикла кадровой карточки не держит.
    assert inheritance.inherited_role_scopes(user.id, "t-fixture-inh-cycle-b") == {}


# ── 8. Выключенный кадровый модуль ─────────────────────────────────────────


@pytest.mark.django_db(transaction=True)
def test_disabled_hr_module_gives_empty_inheritance_and_logs_fallback(
        user, two_company_schemas, service_off, caplog):
    holding, subsidiary = two_company_schemas
    _link(subsidiary, holding)

    role = Role.objects.create(code="r-hr-gate", title="Роль")
    _grant_serving_position(holding, user, role, weight=1)

    # "Выключенный у КОМПАНИИ ЗАПРОСА не мешает наследованию приехать": hr —
    # CORE_MODULE (apps/core/services.py), и компанейский рубильник
    # CompanyModule на него в принципе не действует. Заявлено явно, а не
    # тихо предположено: наследование обязано остаться на месте, даже если у
    # ДОЧЕРНЕЙ (запрошенной) компании стоит запись CompanyModule(hr, off).
    CompanyModule.objects.create(
        company=Company.objects.get(slug=subsidiary), app_label="hr", enabled=False)
    assert inheritance.inherited_role_scopes(user.id, subsidiary) == {
        role.id: (ScopeKind.COMPANY, None)}

    # "Выключенный hr у ПРЕДКА" — единственный рубильник, который на hr
    # реально действует, — глобальный ServiceStatus (module bypasses
    # CompanyModule as core). Наследование обязано опустеть, и это обязано
    # быть СЛЫШНО через fallback(expected=True), а не тихим нулём.
    with caplog.at_level(logging.INFO, logger="htqweb.fallback"):
        with service_off("hr"):
            assert inheritance.inherited_role_scopes(user.id, subsidiary) == {}
    assert "FALLBACK" in caplog.text
    assert "access.inheritance.hr_unavailable" in caplog.text


# ── 9. Разлом схемы предка — code review finding, не «hr выключен» ─────────


@pytest.mark.django_db(transaction=True)
def test_ancestor_schema_fault_alerts_loudly_and_does_not_poison_caller_transaction(
        user, two_company_schemas, monkeypatch, caplog, fallback_log_mode):
    """Осиротевшая строка реестра (CLAUDE.md) — НЕ то же самое, что hr --off.

    Настоящую пропавшую физическую схему здесь не воспроизвести: тестовая БД
    держит ``hr_employee`` прямо в ``public``, и ``SET search_path`` на
    несуществующую ``co_<slug>`` молча проваливается в ``public``, ничего не
    роняя. Поэтому ``hr.get_employee_brief`` подменяется на функцию, которая
    сама бьёт РЕАЛЬНЫМ битым SQL (запрос к несуществующей таблице) в ТОМ ЖЕ
    соединении — это настоящая, а не сочинённая ``django.db.DatabaseError``,
    и она по-настоящему переводит текущую транзакцию Postgres в состояние
    отказа, ровно как это сделал бы запрос к ``hr_employee`` в схеме без
    физических таблиц.

    ``fallback_log_mode`` (``FALLBACK_MODE=log``) — намеренно: это ПРОДовое
    поведение подмены (тихое логирование и продолжение обхода). Дефолт
    settings/test.py — strict, и там ``expected=False`` поднял бы
    ``FallbackNotAllowed`` вместо лога — здесь проверяется как раз то, что
    происходит, когда подмена РАЗРЕШЕНА, потому что это и есть то поведение,
    которое обязано быть слышно на проде.
    """
    holding, subsidiary = two_company_schemas
    _link(subsidiary, holding)

    def _broken_read(_uid):
        # Настоящий отказ Postgres, не питоновский muляж: транзакция после
        # этого в состоянии aborted, пока не будет ROLLBACK (или ROLLBACK TO
        # SAVEPOINT) — ровно то, от чего должен защищать собственный
        # transaction.atomic() внутри inherited_role_scopes.
        with connection.cursor() as cur:
            cur.execute("SELECT * FROM htqweb_test_inheritance_no_such_table")
        return None  # pragma: no cover — cur.execute всегда падает раньше

    monkeypatch.setattr("apps.hr.interface.get_employee_brief", _broken_read)

    with caplog.at_level(logging.INFO, logger="htqweb.fallback"):
        with transaction.atomic():
            # (a) Ни бросить наружу, ни зависнуть — предок просто не даёт
            # ролей.
            result = inheritance.inherited_role_scopes(user.id, subsidiary)
            assert result == {}

            # (c) Транзакция ВЫЗЫВАЮЩЕГО не отравлена: обычный запрос сразу
            # после — в ТОЙ ЖЕ внешней atomic()-транзакции — обязан пройти,
            # а не упасть TransactionManagementError из-за прерванной
            # транзакции. Без собственного savepoint внутри
            # inherited_role_scopes это исключение здесь и получили бы.
            assert Company.objects.filter(slug=subsidiary).exists()

    # (b) Слышно и ОТЛИЧИМО от "hr выключен": свой site, уровень WARNING
    # (а не INFO — это и есть разница между expected=False и expected=True).
    fault_records = [
        r for r in caplog.records
        if "access.inheritance.ancestor_schema_unavailable" in r.getMessage()
    ]
    assert len(fault_records) == 1
    assert fault_records[0].levelname == "WARNING"
    assert "access.inheritance.hr_unavailable" not in caplog.text
