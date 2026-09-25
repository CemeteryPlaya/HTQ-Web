"""``manage.py access_backfill_basic`` — раздача базовой роли (блок I, задача 4,
раунд правок 1).

Проверки — из требования ревью: выдаётся всем действующим участникам, повторный
прогон не плодит, ``--dry-run`` не пишет. Плюс две границы, без которых раздача
«всем» превращается в раздачу «кому попало»: неактивная учётка и человек без
членства в компании роль НЕ получают.

``apps.companies`` импортируется напрямую (не через ``interface``) — нормально
ИМЕННО в ``tests/``: ``apps/core/tests/test_app_isolation.py`` каталоги тестов
не сканирует (см. его докстринг и ``test_backfill_positions.py``, который
делает то же с ``apps.hr``).
"""

from __future__ import annotations

import importlib

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.access.management.commands.access_backfill_basic import ROLE_CODE
from apps.access.models import Role, RoleAssignment, ScopeKind
from apps.companies.models import Company, CompanyKind
from apps.users.models import User, UserStatus

SLUG = "backfill-basic-co"


def _run(**kwargs) -> None:
    call_command("access_backfill_basic", verbosity=1, **kwargs)


@pytest.fixture
def company(db):
    return Company.objects.create(slug=SLUG, name="Перенос",
                                  kind=CompanyKind.SERVICE)


def _user(username: str, *, status=UserStatus.ACTIVE) -> User:
    return User.objects.create(username=username, email=f"{username}@htq.test",
                               password="x", status=status)


def _member(company: Company, username: str, *, status=UserStatus.ACTIVE) -> User:
    from apps.companies.models import CompanyMembership

    user = _user(username, status=status)
    CompanyMembership.objects.create(company=company, user_id=user.id)
    return user


def _has_role(user: User) -> bool:
    return RoleAssignment.objects.filter(
        company_slug=SLUG, user_id=user.id, role__code=ROLE_CODE,
        scope_kind=ScopeKind.COMPANY, scope_id=None,
    ).exists()


@pytest.mark.django_db
def test_role_code_matches_the_seed_migration():
    """Код роли заморожен литералом — он обязан совпасть с сидом ``access/0004``."""
    seed = importlib.import_module("apps.access.migrations.0004_seed_employee_role")
    assert ROLE_CODE == seed.ROLE_CODE
    assert Role.objects.filter(code=ROLE_CODE).exists()


@pytest.mark.django_db
def test_grants_to_every_active_member(company, capsys):
    alice = _member(company, "alice")
    bob = _member(company, "bob")

    _run(company=SLUG)

    assert _has_role(alice) and _has_role(bob)
    out = capsys.readouterr().out
    assert "выдана сейчас 2" in out
    assert "уже была у 0" in out


@pytest.mark.django_db
def test_suspended_member_gets_nothing(company):
    """Членство переживает увольнение — права по нему одному раздавать нельзя."""
    fired = _member(company, "fired", status=UserStatus.SUSPENDED)

    _run(company=SLUG)

    assert not _has_role(fired)


@pytest.mark.django_db
def test_user_outside_the_company_gets_nothing(company):
    """Роль действует в компании: человеку без членства она не значит ничего."""
    stranger = _user("stranger")

    _run(company=SLUG)

    assert not _has_role(stranger)


@pytest.mark.django_db
def test_second_run_does_not_duplicate(company, capsys):
    alice = _member(company, "alice")

    _run(company=SLUG)
    capsys.readouterr()
    _run(company=SLUG)

    assert RoleAssignment.objects.filter(company_slug=SLUG, user_id=alice.id).count() == 1
    out = capsys.readouterr().out
    assert "выдана сейчас 0" in out
    assert "уже была у 1" in out


@pytest.mark.django_db
def test_dry_run_writes_nothing(company, capsys):
    alice = _member(company, "alice")

    _run(company=SLUG, dry_run=True)

    assert not _has_role(alice)
    out = capsys.readouterr().out
    assert "[dry-run]" in out
    assert "выдана сейчас 1" in out


@pytest.mark.django_db
def test_unknown_company_is_an_error(db):
    with pytest.raises(CommandError):
        _run(company="нет-такой")


@pytest.mark.django_db
def test_all_active_companies_without_the_flag(db, capsys):
    """Без ``--company`` обходятся все действующие компании — как у переноса
    должностей."""
    first = Company.objects.create(slug="bb-first", name="Первая",
                                   kind=CompanyKind.SERVICE)
    second = Company.objects.create(slug="bb-second", name="Вторая",
                                    kind=CompanyKind.SERVICE)
    from apps.companies.models import CompanyMembership

    for company, username in ((first, "one"), (second, "two")):
        user = _user(username)
        CompanyMembership.objects.create(company=company, user_id=user.id)

    _run()

    out = capsys.readouterr().out
    assert "bb-first" in out and "bb-second" in out
    assert RoleAssignment.objects.filter(role__code=ROLE_CODE).count() == 2


@pytest.mark.django_db
def test_company_without_members_grants_nothing_and_says_so(company, capsys):
    """Блок I.2, R7: компания без единого участника — команда не падает, не
    пишет ни одного назначения и говорит об этом в сводке отдельной строкой
    (без членства токен на поддомен не выпускается — «выдали 0» здесь не
    успех, а симптом, который человек должен увидеть)."""
    _user("stranger")  # учётка есть, членства нет — не участник

    _run(company=SLUG)

    assert not RoleAssignment.objects.filter(company_slug=SLUG).exists()
    out = capsys.readouterr().out
    assert f"Компания {SLUG}: участников с действующей учёткой 0" in out
    assert "выдана сейчас 0" in out
    assert "уже была у 0" in out
    assert "участников с действующей учёткой нет" in out
