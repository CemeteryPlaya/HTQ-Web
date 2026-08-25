"""Tests for ``apps/users/interface.py`` (Task 2.7, Part C).

Covers the two functions the interface exposes to other apps
(``get_user_brief``, ``get_users_brief``): correct shape, unknown-id
handling, and the ``require_service("users")`` guard raising
``ServiceDisabled`` when the app is turned off — mirroring
``apps/cms/tests`` coverage of ``apps/cms/interface.py`` (there isn't a
dedicated cms interface test file today; this establishes the pattern for
users, which future apps' interface tests should follow too).
"""

from __future__ import annotations

import pytest

from apps.core.models import ServiceStatus
from apps.core.services import ServiceDisabled
from apps.users import interface
from apps.users.models import User, UserStatus


def _disable_users():
    ServiceStatus.objects.update_or_create(app_label="users", defaults={"enabled": False})


@pytest.fixture
def alice(db):
    u = User.objects.create(username="alice", email="alice@htq.test",
                             status=UserStatus.ACTIVE, first_name="Alice", last_name="Smith")
    u.set_password("S3cret!")
    u.save()
    return u


@pytest.fixture
def bob_no_name(db):
    """No first/last name set — exercises the display_name/username fallback."""
    u = User.objects.create(username="bobnoname", email="bob@htq.test",
                             status=UserStatus.ACTIVE)
    u.set_password("S3cret!")
    u.save()
    return u


@pytest.fixture
def suspended(db):
    u = User.objects.create(username="suspy", email="suspy@htq.test",
                             status=UserStatus.SUSPENDED, first_name="Sus", last_name="Pended")
    u.set_password("S3cret!")
    u.save()
    return u


# ── get_user_brief ───────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_get_user_brief_shape(alice):
    brief = interface.get_user_brief(alice.id)
    assert set(brief) == {"id", "username", "email", "full_name", "is_active"}
    assert brief["id"] == alice.id
    assert brief["username"] == "alice"
    assert brief["email"] == "alice@htq.test"
    assert brief["full_name"] == "Alice Smith"
    assert brief["is_active"] is True


@pytest.mark.django_db
def test_get_user_brief_full_name_falls_back_to_username(bob_no_name):
    brief = interface.get_user_brief(bob_no_name.id)
    assert brief["full_name"] == "bobnoname"


@pytest.mark.django_db
def test_get_user_brief_is_active_false_for_suspended(suspended):
    brief = interface.get_user_brief(suspended.id)
    assert brief["is_active"] is False


@pytest.mark.django_db
def test_get_user_brief_unknown_id_returns_none(db):
    assert interface.get_user_brief(999_999) is None


@pytest.mark.django_db
def test_get_user_brief_raises_when_users_disabled(alice):
    _disable_users()
    with pytest.raises(ServiceDisabled):
        interface.get_user_brief(alice.id)


# ── get_users_brief ──────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_get_users_brief_bulk_shape(alice, bob_no_name):
    briefs = interface.get_users_brief([alice.id, bob_no_name.id])
    assert len(briefs) == 2
    by_id = {b["id"]: b for b in briefs}
    assert set(by_id) == {alice.id, bob_no_name.id}
    for b in briefs:
        assert set(b) == {"id", "username", "email", "full_name", "is_active"}


@pytest.mark.django_db
def test_get_users_brief_unknown_ids_absent_not_errored(alice):
    briefs = interface.get_users_brief([alice.id, 999_999])
    assert {b["id"] for b in briefs} == {alice.id}


@pytest.mark.django_db
def test_get_users_brief_empty_input_returns_empty_list(db):
    assert interface.get_users_brief([]) == []


@pytest.mark.django_db
def test_get_users_brief_raises_when_users_disabled(alice):
    _disable_users()
    with pytest.raises(ServiceDisabled):
        interface.get_users_brief([alice.id])


@pytest.mark.django_db
def test_get_users_brief_one_query(alice, bob_no_name, django_assert_num_queries):
    """Bulk fetch is one query against the User table. Call once first so
    require_service("users")'s own ServiceStatus lookup is served from the
    (already-warm) 5s cache during the timed call — otherwise its own DB hit
    would be counted here too and this would really be testing
    require_service's cache, not get_users_brief's query count."""
    interface.get_users_brief([alice.id])
    with django_assert_num_queries(1):
        interface.get_users_brief([alice.id, bob_no_name.id])


# ── list_users_brief ──────────────────────────────────────────────────────────


# patronymic/phone добавлены вместе со сверкой идентичности Сотрудник<->Аккаунт
# (docs/superpowers/specs/2026-08-25-hr-identity-sync-design.md §10): форма
# создания сотрудника сеет ими карточку, чтобы HR не перепечатывал отчество и
# телефон с того же экрана, где они уже есть. bio/avatar_url сюда НЕ входят —
# они приходят только точечным get_user_profile_for_hr.
OPTION_FIELDS = {"id", "username", "email", "first_name", "last_name",
                 "patronymic", "phone", "full_name", "is_active"}


@pytest.mark.django_db
def test_list_users_brief_shape(alice):
    rows = interface.list_users_brief()
    row = next(r for r in rows if r["id"] == alice.id)
    assert set(row) == OPTION_FIELDS
    assert row["username"] == "alice"
    assert row["email"] == "alice@htq.test"
    assert row["first_name"] == "Alice"
    assert row["last_name"] == "Smith"
    assert row["full_name"] == "Alice Smith"
    assert row["is_active"] is True


@pytest.mark.django_db
def test_list_users_brief_includes_non_active_users(alice, suspended):
    """Unlike apps.users.services.options_service.list_user_options (the
    ACTIVE-only picker), this interface primitive does NOT filter by status —
    hr's original list_user_options proxied user-service's admin listing,
    which returns every user regardless of status. Callers filter further
    (messenger) using the returned is_active if they need to."""
    ids = {r["id"] for r in interface.list_users_brief()}
    assert suspended.id in ids
    assert alice.id in ids


@pytest.mark.django_db
def test_list_users_brief_is_active_reflects_status(suspended):
    row = next(r for r in interface.list_users_brief() if r["id"] == suspended.id)
    assert row["is_active"] is False


@pytest.mark.django_db
def test_list_users_brief_search_matches_first_name(alice, bob_no_name):
    rows = interface.list_users_brief(search="Alice")
    assert {r["id"] for r in rows} == {alice.id}


@pytest.mark.django_db
def test_list_users_brief_search_matches_last_name(alice):
    rows = interface.list_users_brief(search="smith")
    assert {r["id"] for r in rows} == {alice.id}


@pytest.mark.django_db
def test_list_users_brief_search_matches_email_case_insensitive(alice):
    rows = interface.list_users_brief(search="ALICE@HTQ")
    assert {r["id"] for r in rows} == {alice.id}


@pytest.mark.django_db
def test_list_users_brief_search_matches_username(bob_no_name):
    rows = interface.list_users_brief(search="bobnoname")
    assert {r["id"] for r in rows} == {bob_no_name.id}


@pytest.mark.django_db
def test_list_users_brief_search_no_match_returns_empty(alice):
    assert interface.list_users_brief(search="zzznomatchzzz") == []


@pytest.mark.django_db
def test_list_users_brief_limit_respected(alice, bob_no_name):
    rows = interface.list_users_brief(limit=1)
    assert len(rows) == 1


@pytest.mark.django_db
def test_list_users_brief_raises_when_users_disabled(alice):
    _disable_users()
    with pytest.raises(ServiceDisabled):
        interface.list_users_brief()


# ── create_user ───────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_create_user_shape():
    row = interface.create_user(email="Newton@HTQ.test", first_name="Isaac", last_name="Newton")
    assert set(row) == OPTION_FIELDS
    assert row["email"] == "newton@htq.test"
    assert row["first_name"] == "Isaac"
    assert row["last_name"] == "Newton"
    assert row["full_name"] == "Isaac Newton"
    assert row["is_active"] is True


@pytest.mark.django_db
def test_create_user_derives_username_from_email_local_part():
    row = interface.create_user(email="jane.doe@htq.test")
    assert row["username"] == "jane.doe"


@pytest.mark.django_db
def test_create_user_persists_must_change_password():
    row = interface.create_user(email="reset-me@htq.test")
    user = User.objects.get(id=row["id"])
    assert user.must_change_password is True


@pytest.mark.django_db
def test_create_user_sets_unusable_temp_password_not_blank():
    row = interface.create_user(email="haspass@htq.test")
    user = User.objects.get(id=row["id"])
    assert user.password  # a real (random) hash was set, not left blank


@pytest.mark.django_db
def test_create_user_duplicate_email_raises(alice):
    with pytest.raises(interface.DuplicateEmail):
        interface.create_user(email="ALICE@htq.test", first_name="Someone", last_name="Else")


@pytest.mark.django_db
def test_create_user_duplicate_username_raises(alice):
    """alice's username is "alice" — an email whose local part derives to the
    same username (but a different address) collides on username, not
    email."""
    with pytest.raises(interface.DuplicateUsername):
        interface.create_user(email="alice@otherdomain.test")


@pytest.mark.django_db
def test_create_user_raises_when_users_disabled():
    _disable_users()
    with pytest.raises(ServiceDisabled):
        interface.create_user(email="whatever@htq.test")
