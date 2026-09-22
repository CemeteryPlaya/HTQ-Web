"""Базовая роль выдаётся при создании членства — рулинг M финальной волны блока I.

``access_backfill_basic`` раздал ``employee-basic`` участникам на день
выкатки, но после него роль не выдавал никто: ни ``company_grant``, ни экран
участников, ни ``tenancy_bootstrap --grant-all`` — новый участник получал 403
на подбор коллег (``users/options``) и весь ``tasks`` (F3 финального ревью).
Теперь её выдаёт единственная точка создания членства
(``apps.companies.services.membership_service.grant_membership``) через
``apps.access.interface.ensure_basic_role``.

Модели ``apps.companies``/``apps.users`` импортируются напрямую — в
``tests/`` это разрешено (сторож границ каталоги тестов не сканирует).
"""

from __future__ import annotations

import importlib

import pytest
from django.core.management import call_command

from apps.access import interface as access
from apps.access.management.commands.access_backfill_basic import ROLE_CODE
from apps.access.models import Level, Role, RoleAssignment, ScopeKind
from apps.access.services.assignment import BASIC_ROLE_CODE
from apps.access.services.errors import UnknownRole
from apps.companies.models import Company, CompanyKind, CompanyMembership
from apps.companies.services import membership_service
from apps.users.models import User, UserStatus

SLUG = "htq-basic"


@pytest.fixture
def company(db):
    return Company.objects.create(slug=SLUG, name="HTQ", kind=CompanyKind.CONSTRUCTION)


def _user(username: str, status=UserStatus.ACTIVE) -> User:
    return User.objects.create(username=username, email=f"{username}@htq.test",
                               password="x", status=status)


def _basic(user_id: int):
    return RoleAssignment.objects.filter(
        company_slug=SLUG, user_id=user_id, role__code=BASIC_ROLE_CODE)


def test_role_code_is_the_one_the_backfill_and_migration_use():
    migration = importlib.import_module("apps.access.migrations.0004_seed_employee_role")
    assert BASIC_ROLE_CODE == ROLE_CODE == migration.ROLE_CODE


@pytest.mark.django_db
def test_seeded_role_exists_and_is_system():
    assert Role.objects.get(code=BASIC_ROLE_CODE).is_system is True


@pytest.mark.django_db
def test_ensure_basic_role_is_idempotent(company):
    user = _user("ivanov")
    assert access.ensure_basic_role(SLUG, user.id) is True
    assert access.ensure_basic_role(SLUG, user.id) is False
    rows = list(_basic(user.id))
    assert len(rows) == 1
    assert rows[0].scope_kind == ScopeKind.COMPANY
    assert rows[0].scope_id is None


@pytest.mark.django_db
def test_missing_role_is_loud_and_leaves_no_membership(company):
    Role.objects.filter(code=BASIC_ROLE_CODE).delete()
    user = _user("petrov")
    with pytest.raises(UnknownRole):
        membership_service.grant_membership(company, user.id)
    assert not CompanyMembership.objects.filter(company=company, user_id=user.id).exists()


@pytest.mark.django_db
def test_new_membership_gets_the_basic_role(company):
    user = _user("sidorov")
    assert membership_service.grant_membership(company, user.id) is True
    assert _basic(user.id).count() == 1
    # Повтор — ни второго членства, ни второго назначения.
    assert membership_service.grant_membership(company, user.id) is False
    assert _basic(user.id).count() == 1
    assert CompanyMembership.objects.filter(company=company, user_id=user.id).count() == 1


@pytest.mark.django_db
def test_existing_membership_is_not_regranted_the_role(company):
    """Роль, снятую у уже состоящего участника, повторный grant не
    возвращает: довыдача существующим — дело ``access_backfill_basic``."""
    user = _user("kuznetsov")
    CompanyMembership.objects.create(company=company, user_id=user.id)
    assert membership_service.grant_membership(company, user.id) is False
    assert not _basic(user.id).exists()


@pytest.mark.django_db
def test_new_member_is_no_longer_locked_out_of_tasks(company):
    """Симптом F3: членство есть, ролей нет — ``none`` на ``tasks``."""
    user = _user("novikov")
    membership_service.grant_membership(company, user.id)
    assert access.permission_level(user, "tasks", SLUG) != Level.NONE
    assert access.permission_level(user, "users", SLUG) != Level.NONE


@pytest.mark.django_db
def test_memberships_endpoint_grants_the_basic_role(client, company):
    from apps.companies.tests.api_helpers import auth, post_json, superuser_token

    user = _user("smirnov")
    res = post_json(client, f"/api/companies/v1/companies/{SLUG}/memberships",
                    {"user_id": user.id}, **auth(superuser_token()))
    assert res.status_code == 201
    assert _basic(user.id).count() == 1


@pytest.mark.django_db
def test_company_grant_all_users_gives_everyone_the_role(company):
    active = [_user(f"active-{i}") for i in range(3)]
    inactive = _user("suspended", status=UserStatus.SUSPENDED)
    call_command("company_grant", company_slug=SLUG, all_users=True)
    for user in active:
        assert _basic(user.id).count() == 1, user.username
    assert not _basic(inactive.id).exists()
