"""access_backfill_services_admin — роль services-admin текущим is_staff."""
from io import StringIO

import pytest
from django.core.management import call_command

from apps.access.models import Role, RoleAssignment
from apps.companies.models import Company, CompanyKind, CompanyMembership
from apps.users.models import User, UserStatus


def _user(name, *, staff=False, superuser=False, status=UserStatus.ACTIVE):
    return User.objects.create(username=name, email=f"{name}@htq.test", password="x",
                               status=status, is_staff=staff, is_superuser=superuser)


@pytest.fixture
def company(db):
    return Company.objects.create(slug="t-sa", name="SA", kind=CompanyKind.SERVICE)


def _run(*args):
    out = StringIO()
    call_command("access_backfill_services_admin", *args, stdout=out)
    return out.getvalue()


def _holders(company_slug):
    role = Role.objects.get(code="services-admin")
    return set(RoleAssignment.objects.filter(company_slug=company_slug, role=role)
               .values_list("user_id", flat=True))


def test_staff_member_gets_the_role_in_his_company(company):
    staff = _user("staff", staff=True)
    CompanyMembership.objects.create(company=company, user_id=staff.id)
    _run()
    assert _holders(company.slug) == {staff.id}


def test_superuser_plain_inactive_and_nonmember_are_skipped(company):
    su = _user("su", staff=True, superuser=True)
    plain = _user("plain")
    gone = _user("gone", staff=True, status=UserStatus.SUSPENDED)
    lonely = _user("lonely", staff=True)
    for u in (su, plain, gone):
        CompanyMembership.objects.create(company=company, user_id=u.id)
    out = _run()
    assert _holders(company.slug) == set()
    assert "lonely" in out or str(lonely.id) in out   # без членства — в сводке


def test_dry_run_writes_nothing_and_rerun_is_idempotent(company):
    staff = _user("staff", staff=True)
    CompanyMembership.objects.create(company=company, user_id=staff.id)
    _run("--dry-run")
    assert _holders(company.slug) == set()
    _run()
    _run()
    assert RoleAssignment.objects.filter(
        company_slug=company.slug, user_id=staff.id,
        role__code="services-admin").count() == 1
