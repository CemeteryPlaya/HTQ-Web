"""Глубина: флаги, пресеты, наследование вниз по реестру и проекция уровней.

Это новая модель прав целиком, поэтому проверяется не только «работает», но и
те три её свойства, ради которых она и заменила прежнюю лестницу:

1. глубина — НАБОР признаков, а не ступень (иначе «удаляет, но не правит»
   выразить нечем);
2. не заданный узел наследует предка, а пустой набор — запрещает (иначе роль
   пришлось бы расписывать по каждому столбцу);
3. прежние уровни остались ответом API, но стали ВЫЧИСЛЯЕМЫМИ.
"""

import pytest

from apps.access import depth, registry
from apps.access.models import Level, Role, RoleAssignment, ScopeKind
from apps.access.services import resolve
from apps.access.tests.helpers import grant

COMPANY = "htq-kz"


def _role_for(user, code: str) -> Role:
    role = Role.objects.create(code=code, title=code)
    RoleAssignment.objects.create(company_slug=COMPANY, user_id=user.id, role=role,
                                  scope_kind=ScopeKind.COMPANY, scope_id=None)
    return role


# ── Пресеты ─────────────────────────────────────────────────────────────────


def test_edit_is_view_plus_input():
    """Определение заказчика: «может редактировать» = «видит и вводит»."""
    assert depth.PRESETS["edit"] >= depth.PRESETS["create"]
    assert depth.VIEW in depth.PRESETS["create"]


def test_delete_does_not_imply_edit():
    """«Может удалять» — право убрать запись, а не переписать её."""
    assert depth.EDIT not in depth.PRESETS["delete"]
    assert depth.DELETE in depth.PRESETS["delete"]


def test_full_is_every_flag():
    assert depth.PRESETS["full"] == frozenset(depth.FLAGS)


def test_preset_is_recognised_back():
    assert depth.preset_of(depth.PRESETS["edit"]) == "edit"


def test_own_combination_has_no_preset():
    """Своя комбинация допустима — интерфейс покажет флаги, а не название."""
    assert depth.preset_of({depth.CREATE}) is None


# ── Реестр ──────────────────────────────────────────────────────────────────


def test_registry_has_three_levels():
    kinds = {row["path"]: row["kind"] for row in registry.nodes()}
    assert kinds["hr"] == registry.MODULE
    assert kinds["hr.employees"] == registry.FUNCTION
    assert kinds["hr.employees.salary"] == registry.FIELD


def test_every_module_is_a_node_even_without_declared_functions():
    """Домен обязан быть в реестре, иначе роль нельзя выдать на него целиком."""
    from apps.core.models import KNOWN_SERVICES

    paths = registry.paths()
    assert set(KNOWN_SERVICES) <= paths


def test_ancestors_go_from_nearest_to_root():
    assert registry.ancestors("hr.employees.salary") == ["hr.employees", "hr"]


# ── Наследование ────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_function_inherits_the_module(user):
    role = _role_for(user, "r1")
    grant(role, "hr", "edit")

    assert resolve.flags_for(user, "hr.employees", COMPANY) == depth.PRESETS["edit"]
    assert resolve.flags_for(user, "hr.employees.salary", COMPANY) == depth.PRESETS["edit"]


@pytest.mark.django_db
def test_nearest_explicit_node_wins(user):
    role = _role_for(user, "r2")
    grant(role, "hr", "full")
    grant(role, "hr.employees", "view")

    assert resolve.flags_for(user, "hr.employees", COMPANY) == depth.PRESETS["view"]
    # Поле наследует ближайшего предка — функцию, а не модуль.
    assert resolve.flags_for(user, "hr.employees.salary", COMPANY) == depth.PRESETS["view"]
    # Соседняя функция по-прежнему берёт своё у модуля.
    assert resolve.flags_for(user, "hr.documents", COMPANY) == depth.PRESETS["full"]


@pytest.mark.django_db
def test_empty_set_is_a_ban_not_a_gap(user):
    """Пустой набор перекрывает разрешение модуля — иначе поле не закрыть."""
    role = _role_for(user, "r3")
    grant(role, "hr", "full")
    grant(role, "hr.employees.salary", "none")

    assert resolve.flags_for(user, "hr.employees", COMPANY) == depth.PRESETS["full"]
    assert resolve.flags_for(user, "hr.employees.salary", COMPANY) == frozenset()


@pytest.mark.django_db
def test_two_roles_are_united_per_node(user):
    viewer = _role_for(user, "viewer")
    grant(viewer, "hr.employees", "view")
    remover = _role_for(user, "remover")
    grant(remover, "hr.employees", "delete")

    flags = resolve.flags_for(user, "hr.employees", COMPANY)
    assert depth.VIEW in flags and depth.DELETE in flags
    assert depth.EDIT not in flags


@pytest.mark.django_db
def test_ban_in_one_role_does_not_cancel_grant_in_another(user):
    """Роли складываются. Запрет — свойство роли, а не пользователя.

    Иначе одна «ограничительная» роль тихо отбирала бы права, выданные другой,
    и понять, почему доступ пропал, можно было бы только сложив все роли в уме.
    """
    allowed = _role_for(user, "allowed")
    grant(allowed, "hr.employees.salary", "view")
    banned = _role_for(user, "banned")
    grant(banned, "hr.employees.salary", "none")

    assert resolve.flags_for(user, "hr.employees.salary", COMPANY) == depth.PRESETS["view"]


@pytest.mark.django_db
def test_can_answers_a_single_flag(user):
    role = _role_for(user, "r4")
    grant(role, "hr.employees", "edit")

    assert resolve.can(user, "hr.employees", depth.EDIT, COMPANY) is True
    assert resolve.can(user, "hr.employees", depth.DELETE, COMPANY) is False


# ── Проекция в прежние уровни ───────────────────────────────────────────────


def test_legacy_projection_rules():
    assert depth.legacy_level(frozenset()) == Level.NONE
    assert depth.legacy_level(depth.PRESETS["view"]) == Level.READ
    assert depth.legacy_level(depth.PRESETS["create"]) == Level.WRITE
    assert depth.legacy_level(depth.PRESETS["edit"]) == Level.WRITE
    # Разрушающая операция — admin: то же правило, что в §10 дизайна стадии 2.
    assert depth.legacy_level(depth.PRESETS["delete"]) == Level.ADMIN


@pytest.mark.django_db
def test_module_level_covers_the_whole_subtree(user):
    """Право на ОДНУ функцию обязано открывать маршруты модуля.

    Иначе человек с доступом к экрану не смог бы на него попасть: маршруты
    гейтятся уровнем модуля, а он считается проекцией глубины.
    """
    role = _role_for(user, "r5")
    grant(role, "hr.employees", "edit")

    assert resolve.permission_level(user, "hr", COMPANY) == Level.WRITE


@pytest.mark.django_db
def test_field_level_ban_does_not_close_the_module(user):
    role = _role_for(user, "r6")
    grant(role, "hr", "view")
    grant(role, "hr.employees.salary", "none")

    assert resolve.permission_level(user, "hr", COMPANY) == Level.READ


@pytest.mark.django_db
def test_depth_map_lists_only_granted_nodes(user):
    role = _role_for(user, "r7")
    grant(role, "hr.employees", "view")

    assert resolve.depth_map(user, COMPANY) == {"hr.employees": ["view"]}


@pytest.mark.django_db
def test_superuser_gets_every_flag_everywhere(superuser):
    assert resolve.flags_for(superuser, "hr.employees.salary", None) == frozenset(depth.FLAGS)


# ── Применимость признаков ──────────────────────────────────────────────────
#
# Не всякая функция описывается CRUD'ом. Ровно этот вопрос и задал заказчик:
# что означает «видеоконференция — только удалять» и пустят ли по такой роли в
# комнату. Правильный ответ — что такая роль не должна заводиться вовсе.


def test_action_node_accepts_only_access_or_no_access():
    assert registry.applicable_flags("conference.join") == frozenset({depth.VIEW})
    assert registry.is_action("conference.join") is True


def test_record_shaped_node_keeps_the_full_crud():
    assert registry.applicable_flags("hr.employees") == frozenset(depth.FLAGS)
    assert registry.is_action("hr.employees") is False


def test_partially_applicable_node():
    """Запись встречи можно посмотреть и удалить, но не «ввести» и не «править»."""
    assert registry.applicable_flags("conference.recordings") == frozenset(
        {depth.VIEW, depth.DELETE})


@pytest.mark.django_db
def test_meaningless_depth_is_refused():
    """«Видеоконференция: только удалять» больше не заводится."""
    from apps.access.services import catalog
    from apps.access.services.errors import DepthNotApplicable

    role = Role.objects.create(code="strange", title="Странная")
    with pytest.raises(DepthNotApplicable):
        catalog.set_permissions(role.id, [
            {"node": "conference.join", "flags": [depth.DELETE]},
        ])


@pytest.mark.django_db
def test_action_node_still_takes_access_and_ban():
    from apps.access.services import catalog

    role = Role.objects.create(code="ok", title="Обычная")
    catalog.set_permissions(role.id, [
        {"node": "conference.join", "preset": "view"},
        {"node": "conference.recordings", "preset": "none"},
    ])
    rows = {row["node"]: row["flags"] for row in catalog.permissions_of(role.id)}
    assert rows == {"conference.join": ["view"], "conference.recordings": []}


@pytest.mark.django_db
def test_module_wide_preset_does_not_leak_into_an_action(user):
    """Полный доступ на модуль не наделяет действие несуществующими признаками.

    Наследование отдаёт узлу набор предка как есть, поэтому у действия он может
    оказаться шире применимого. Значение имеет только то, что применимо, —
    и проверять надо именно это, иначе «полный доступ на конференции» выглядел
    бы как право «удалять вход».
    """
    role = Role.objects.create(code="wide", title="Широкая")
    RoleAssignment.objects.create(company_slug=COMPANY, user_id=user.id, role=role,
                                  scope_kind=ScopeKind.COMPANY, scope_id=None)
    grant(role, "conference", "full")

    flags = resolve.flags_for(user, "conference.join", COMPANY)
    applicable = registry.applicable_flags("conference.join")
    assert flags & applicable == {depth.VIEW}


def test_messenger_separates_the_ordinary_user_from_the_administrator():
    """Граница проходит по функциям, а не по глубине одного узла."""
    assert registry.is_action("messenger.chats") is True
    assert registry.applicable_flags("messenger.rooms") == frozenset(depth.FLAGS)
    assert registry.applicable_flags("messenger.moderation") == frozenset(
        {depth.VIEW, depth.DELETE})
