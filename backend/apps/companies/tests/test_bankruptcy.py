"""Банкротство с преемником (спека docs/plans/2026-09-26-company-bankruptcy-spec.md).

Поверх ``two_company_schemas``: архив пересобирает сводки холдинга, а им
нужны настоящие схемы. Схему ``holding`` фикстура из conftest.py не знает —
сносим её на выходе, как ``two_companies`` в test_company_archive.py.
"""

import io

import pytest
from django.core.management import CommandError, call_command
from django.db import connection

from apps.access.models import RoleAssignment
from apps.companies.models import Company, CompanyMembership, CompanyStatus
from apps.companies.services import lifecycle
from apps.users.models import User, UserStatus


@pytest.fixture
def pair(two_company_schemas):
    try:
        yield list(two_company_schemas)  # [bankrupt, successor]
    finally:
        with connection.cursor() as cur:
            cur.execute("DROP SCHEMA IF EXISTS holding CASCADE")


def _user(username, status=UserStatus.ACTIVE):
    return User.objects.create(username=username, email=f"{username}@htq.test",
                               password="x", status=status)


def _member(slug, user, *, is_default=False):
    return CompanyMembership.objects.create(
        company=Company.objects.get(slug=slug), user_id=user.id, is_default=is_default)


def _member_ids(slug):
    return set(CompanyMembership.objects.filter(company__slug=slug)
               .values_list("user_id", flat=True))


@pytest.mark.django_db
def test_members_move_to_successor_with_basic_role(pair):
    dead, heir = pair
    alice, bob = _user("alice"), _user("bob")
    _member(dead, alice)
    _member(dead, bob)

    result = lifecycle.bankrupt_company(dead, heir)

    assert _member_ids(heir) == {alice.id, bob.id}
    assert RoleAssignment.objects.filter(company_slug=heir, user_id=alice.id,
                                         role__code="employee-basic").exists()
    assert (result.members_total, result.members_granted, result.members_already) == (2, 2, 0)
    assert result.archived is True and result.dry_run is False
    company = Company.objects.get(slug=dead)
    assert company.status == CompanyStatus.ARCHIVED
    assert company.successor.slug == heir


@pytest.mark.django_db
def test_existing_member_of_successor_is_not_touched(pair):
    """Уже состоящий в преемнике: членство не задваивается, роль не
    довыдаётся — снятая человеком роль повторным grant'ом не возвращается."""
    dead, heir = pair
    carol = _user("carol")
    _member(dead, carol)
    _member(heir, carol)  # напрямую, без grant — роли у неё в heir нет

    result = lifecycle.bankrupt_company(dead, heir)

    assert CompanyMembership.objects.filter(company__slug=heir, user_id=carol.id).count() == 1
    assert not RoleAssignment.objects.filter(company_slug=heir, user_id=carol.id).exists()
    assert (result.members_granted, result.members_already) == (0, 1)


@pytest.mark.django_db
def test_inactive_account_is_not_carried_over(pair):
    dead, heir = pair
    gone = _user("gone", status=UserStatus.SUSPENDED)
    _member(dead, gone)

    result = lifecycle.bankrupt_company(dead, heir)

    assert gone.id not in _member_ids(heir)
    assert result.members_total == 0


@pytest.mark.django_db
def test_default_company_flag_moves_to_successor(pair):
    dead, heir = pair
    dora, eve = _user("dora"), _user("eve")
    _member(dead, dora, is_default=True)
    _member(dead, eve)

    lifecycle.bankrupt_company(dead, heir)

    assert CompanyMembership.objects.get(company__slug=heir, user_id=dora.id).is_default is True
    assert CompanyMembership.objects.get(company__slug=heir, user_id=eve.id).is_default is False


@pytest.mark.django_db
def test_dry_run_changes_nothing(pair):
    dead, heir = pair
    frank = _user("frank")
    _member(dead, frank)

    result = lifecycle.bankrupt_company(dead, heir, dry_run=True)

    assert result.dry_run is True
    assert (result.members_total, result.members_granted, result.members_already) == (1, 1, 0)
    assert result.archived is False
    assert _member_ids(heir) == set()
    company = Company.objects.get(slug=dead)
    assert company.status == CompanyStatus.ACTIVE and company.successor is None


@pytest.mark.django_db
def test_company_cannot_be_its_own_successor(pair):
    dead, _heir = pair
    with pytest.raises(lifecycle.SuccessorInvalid) as exc:
        lifecycle.bankrupt_company(dead, dead)
    assert (exc.value.status, exc.value.code) == (422, "successor_invalid")


@pytest.mark.django_db
def test_archived_successor_is_refused(pair):
    dead, heir = pair
    Company.objects.filter(slug=heir).update(status=CompanyStatus.ARCHIVED)
    with pytest.raises(lifecycle.SuccessorInvalid):
        lifecycle.bankrupt_company(dead, heir)


@pytest.mark.django_db
def test_unknown_company_or_successor_is_not_found(pair):
    dead, heir = pair
    with pytest.raises(lifecycle.CompanyNotFound):
        lifecycle.bankrupt_company("no-such", heir)
    with pytest.raises(lifecycle.CompanyNotFound):
        lifecycle.bankrupt_company(dead, "no-such")


@pytest.mark.django_db
def test_other_successor_is_a_conflict(pair):
    dead, heir = pair
    third = Company.objects.create(slug="t-third", name="t-third", kind="service")
    Company.objects.filter(slug=dead).update(successor=third)
    with pytest.raises(lifecycle.SuccessorConflict) as exc:
        lifecycle.bankrupt_company(dead, heir)
    assert (exc.value.status, exc.value.code) == (409, "successor_conflict")


@pytest.mark.django_db
def test_repeat_with_same_successor_is_idempotent(pair):
    """Повтор после сбоя на середине: та же пара довыдаёт недостающее."""
    dead, heir = pair
    gina, hank = _user("gina"), _user("hank")
    _member(dead, gina)
    lifecycle.bankrupt_company(dead, heir)
    _member(dead, hank)  # появился в архиве позже (например, перенос не дошёл)

    result = lifecycle.bankrupt_company(dead, heir)

    assert _member_ids(heir) == {gina.id, hank.id}
    assert (result.members_granted, result.members_already, result.archived) == (1, 1, False)


@pytest.mark.django_db
def test_already_archived_company_without_successor_can_be_closed(pair):
    dead, heir = pair
    lifecycle.archive_company(dead)

    result = lifecycle.bankrupt_company(dead, heir)

    assert result.archived is False
    assert Company.objects.get(slug=dead).successor.slug == heir


@pytest.mark.django_db
def test_restore_clears_successor_and_keeps_memberships(pair):
    dead, heir = pair
    ivan = _user("ivan")
    _member(dead, ivan)
    lifecycle.bankrupt_company(dead, heir)

    lifecycle.restore_company(dead)

    company = Company.objects.get(slug=dead)
    assert company.status == CompanyStatus.ACTIVE and company.successor is None
    assert ivan.id in _member_ids(heir)


@pytest.mark.django_db
def test_command_prints_summary_and_supports_dry_run(pair):
    dead, heir = pair
    _member(dead, _user("jane"))
    out = io.StringIO()

    call_command("company_bankrupt", "--company", dead, "--successor", heir,
                 "--dry-run", stdout=out)
    assert "получат доступ" in out.getvalue()
    assert Company.objects.get(slug=dead).status == CompanyStatus.ACTIVE

    out = io.StringIO()
    call_command("company_bankrupt", "--company", dead, "--successor", heir, stdout=out)
    assert Company.objects.get(slug=dead).status == CompanyStatus.ARCHIVED
    assert "в архив" in out.getvalue()


@pytest.mark.django_db
def test_command_error_is_a_command_error(pair):
    dead, _heir = pair
    with pytest.raises(CommandError, match="собственным преемником"):
        call_command("company_bankrupt", "--company", dead, "--successor", dead)
