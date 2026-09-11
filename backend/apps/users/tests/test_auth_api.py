"""Contract tests for ``/api/users/v1/{token,token/refresh,admin-session}/*``.

Mirrors ``services/user/app/api/v1/auth.py`` (the FastAPI original) field for
field, status for status, error string for error string. Tokens for the
refresh/decode assertions are built with real ``jwt.encode``/``htqweb.authn``
(no mocking of ``decode_token``) — same style as
``apps/cms/tests/test_contact_requests_api.py``.
"""

import jwt as pyjwt
import pytest
from django.conf import settings
from django.test import Client

from apps.companies.models import Company, CompanyKind, CompanyMembership
from apps.users.models import User, UserStatus
from htqweb.authn.jwt import decode_token, issue_token_pair

BASE = "/api/users/v1"


@pytest.fixture
def active_user(db):
    u = User.objects.create(username="alice", email="alice@htq.test", password="x",
                            status=UserStatus.ACTIVE)
    u.set_password("S3cret!")
    u.save()
    return u


@pytest.fixture
def superuser(db):
    u = User.objects.create(username="root", email="root@htq.test", password="x",
                            status=UserStatus.ACTIVE, is_superuser=True)
    u.set_password("Adm1n!Pass")
    u.save()
    return u


@pytest.fixture
def staff_user(db):
    u = User.objects.create(username="staffer", email="staffer@htq.test", password="x",
                            status=UserStatus.ACTIVE, is_staff=True)
    u.set_password("Staff1!Pass")
    u.save()
    return u


# ── POST token/ — login ──────────────────────────────────────────────────────


@pytest.mark.django_db
def test_login_by_email_200_with_all_three_fields(active_user):
    resp = Client().post(f"{BASE}/token/", data={
        "email": "alice@htq.test", "password": "S3cret!",
    }, content_type="application/json")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"access", "refresh", "token_type"}
    assert body["token_type"] == "Bearer"
    assert body["access"]
    assert body["refresh"]


@pytest.mark.django_db
def test_login_by_username_200(active_user):
    resp = Client().post(f"{BASE}/token/", data={
        "email": "alice", "password": "S3cret!",
    }, content_type="application/json")
    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "Bearer"


@pytest.mark.django_db
def test_login_wrong_password_401_invalid_credentials(active_user):
    resp = Client().post(f"{BASE}/token/", data={
        "email": "alice@htq.test", "password": "wrong",
    }, content_type="application/json")
    assert resp.status_code == 401
    assert resp.json() == {"detail": "Invalid credentials"}


@pytest.mark.django_db
def test_login_unknown_user_401_invalid_credentials(db):
    resp = Client().post(f"{BASE}/token/", data={
        "email": "nobody@htq.test", "password": "whatever",
    }, content_type="application/json")
    assert resp.status_code == 401
    assert resp.json() == {"detail": "Invalid credentials"}


@pytest.mark.django_db
@pytest.mark.parametrize("status", [UserStatus.PENDING, UserStatus.SUSPENDED])
def test_login_correct_password_inactive_status_401_not_activated(db, status):
    u = User.objects.create(username="pending1", email="pending1@htq.test",
                            password="x", status=status)
    u.set_password("S3cret!")
    u.save()
    resp = Client().post(f"{BASE}/token/", data={
        "email": "pending1@htq.test", "password": "S3cret!",
    }, content_type="application/json")
    assert resp.status_code == 401
    assert resp.json() == {"detail": "Account is not activated"}


@pytest.mark.django_db
def test_login_updates_last_login(active_user):
    assert active_user.last_login is None
    resp = Client().post(f"{BASE}/token/", data={
        "email": "alice@htq.test", "password": "S3cret!",
    }, content_type="application/json")
    assert resp.status_code == 200
    active_user.refresh_from_db()
    assert active_user.last_login is not None


@pytest.mark.django_db
def test_login_wrong_password_inactive_status_still_invalid_credentials(db):
    """auth_service.authenticate checks status BEFORE password (ported
    verbatim from the FastAPI original's obtain_token — see the docstring
    on authenticate()). So a non-ACTIVE user gets 'Account is not activated'
    regardless of whether the submitted password happens to be right OR
    wrong — the status check short-circuits before check_password runs."""
    u = User.objects.create(username="pending2", email="pending2@htq.test",
                            password="x", status=UserStatus.PENDING)
    u.set_password("S3cret!")
    u.save()
    resp = Client().post(f"{BASE}/token/", data={
        "email": "pending2@htq.test", "password": "totally-wrong",
    }, content_type="application/json")
    assert resp.status_code == 401
    assert resp.json() == {"detail": "Account is not activated"}


@pytest.mark.django_db
def test_failed_login_does_not_touch_last_login(active_user):
    assert active_user.last_login is None
    resp = Client().post(f"{BASE}/token/", data={
        "email": "alice@htq.test", "password": "wrong",
    }, content_type="application/json")
    assert resp.status_code == 401
    active_user.refresh_from_db()
    assert active_user.last_login is None


@pytest.mark.django_db
def test_login_issued_access_token_decodes_with_full_claim_set(active_user):
    resp = Client().post(f"{BASE}/token/", data={
        "email": "alice@htq.test", "password": "S3cret!",
    }, content_type="application/json")
    access = resp.json()["access"]
    payload = decode_token(access)
    assert payload.user_id == active_user.id
    assert payload.username == active_user.username
    assert payload.email == active_user.email
    assert payload.token_type == "access"
    assert payload.is_staff is False
    assert payload.is_superuser is False
    assert payload.is_admin is False


# ── POST token/refresh/ ──────────────────────────────────────────────────────


@pytest.mark.django_db
def test_refresh_with_real_refresh_token_200_new_access(active_user):
    pair = issue_token_pair(active_user)
    resp = Client().post(f"{BASE}/token/refresh/", data={
        "refresh": pair["refresh"],
    }, content_type="application/json")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"access", "token_type"}
    assert body["token_type"] == "Bearer"
    new_payload = decode_token(body["access"])
    assert new_payload.user_id == active_user.id
    assert new_payload.token_type == "access"


@pytest.mark.django_db
def test_refresh_with_access_token_401(active_user):
    pair = issue_token_pair(active_user)
    resp = Client().post(f"{BASE}/token/refresh/", data={
        "refresh": pair["access"],
    }, content_type="application/json")
    assert resp.status_code == 401
    assert "detail" in resp.json()


@pytest.mark.django_db
def test_refresh_with_garbage_401(db):
    resp = Client().post(f"{BASE}/token/refresh/", data={
        "refresh": "not-a-jwt-at-all",
    }, content_type="application/json")
    assert resp.status_code == 401
    assert "detail" in resp.json()


# ── Компания запроса (findings #2): и login, и refresh обязаны выдать токен
#    компании X-HTQ-Company, а не компании по умолчанию — иначе пользователь
#    на чужом (для default_company_slug) поддомене либо заперт после
#    переключения (refresh), либо вовсе не может войти (login, см.
#    followup-b-report.md — координатор указал на этот же дефект во входе).
# ─────────────────────────────────────────────────────────────────────────


@pytest.fixture
def companies(db):
    kz = Company.objects.create(slug="htq-kz", name="KZ", kind=CompanyKind.REGIONAL)
    uz = Company.objects.create(slug="htq-uz", name="UZ", kind=CompanyKind.REGIONAL)
    return kz, uz


@pytest.mark.django_db
def test_login_with_company_header_issues_token_for_that_company(active_user, companies):
    """Вход на uz.-поддомене должен сразу выдать токен uz, а не компании по
    умолчанию (kz) — иначе следующий же запрос получает 403 без всякого
    refresh, который мог бы это поправить (login выдаёт первый токен)."""
    kz, uz = companies
    CompanyMembership.objects.create(user_id=active_user.id, company=kz, is_default=True)
    CompanyMembership.objects.create(user_id=active_user.id, company=uz)

    resp = Client().post(f"{BASE}/token/", data={
        "email": "alice@htq.test", "password": "S3cret!",
    }, content_type="application/json", HTTP_X_HTQ_COMPANY="htq-uz")

    assert resp.status_code == 200
    payload = decode_token(resp.json()["access"])
    assert payload.company == "htq-uz"


@pytest.mark.django_db
def test_login_with_company_header_not_a_member_403_forbidden(active_user, companies):
    """Вход на поддомене чужой компании отказывает, а не выдаёт токен с
    компанией по умолчанию, который всё равно не совпал бы с поддоменом."""
    kz, uz = companies
    CompanyMembership.objects.create(user_id=active_user.id, company=kz, is_default=True)

    resp = Client().post(f"{BASE}/token/", data={
        "email": "alice@htq.test", "password": "S3cret!",
    }, content_type="application/json", HTTP_X_HTQ_COMPANY="htq-uz")

    assert resp.status_code == 403
    assert resp.json() == {"detail": "Forbidden"}


@pytest.mark.django_db
def test_login_without_company_header_keeps_default_company_behaviour(active_user, companies):
    """Заголовка нет (общий домен, переходный период) — поведение прежнее:
    компания по умолчанию, без отказа."""
    kz, uz = companies
    CompanyMembership.objects.create(user_id=active_user.id, company=kz, is_default=True)
    CompanyMembership.objects.create(user_id=active_user.id, company=uz)

    resp = Client().post(f"{BASE}/token/", data={
        "email": "alice@htq.test", "password": "S3cret!",
    }, content_type="application/json")

    assert resp.status_code == 200
    payload = decode_token(resp.json()["access"])
    assert payload.company == "htq-kz"


@pytest.mark.django_db
def test_refresh_with_company_header_issues_token_for_that_company(active_user, companies):
    """Пользователь состоит в обеих компаниях. Переход на uz.-поддомен должен
    обменять refresh на access ИМЕННО для uz, а не для компании по умолчанию
    (kz) — именно это было дефектом."""
    kz, uz = companies
    CompanyMembership.objects.create(user_id=active_user.id, company=kz, is_default=True)
    CompanyMembership.objects.create(user_id=active_user.id, company=uz)
    pair = issue_token_pair(active_user)  # refresh несёт только user_id, без company

    resp = Client().post(f"{BASE}/token/refresh/", data={
        "refresh": pair["refresh"],
    }, content_type="application/json", HTTP_X_HTQ_COMPANY="htq-uz")

    assert resp.status_code == 200
    new_payload = decode_token(resp.json()["access"])
    assert new_payload.company == "htq-uz"


@pytest.mark.django_db
def test_refresh_with_company_header_not_a_member_403_forbidden(active_user, companies):
    """Без проверки членства обмен выдал бы токен любой компании, чей
    поддомен просто открыли — дыра, которую закрывает это ревью."""
    kz, uz = companies
    CompanyMembership.objects.create(user_id=active_user.id, company=kz, is_default=True)
    pair = issue_token_pair(active_user)

    resp = Client().post(f"{BASE}/token/refresh/", data={
        "refresh": pair["refresh"],
    }, content_type="application/json", HTTP_X_HTQ_COMPANY="htq-uz")

    assert resp.status_code == 403
    assert resp.json() == {"detail": "Forbidden"}


@pytest.mark.django_db
def test_refresh_without_company_header_keeps_default_company_behaviour(active_user, companies):
    """Заголовка нет (общий домен, переходный период) — поведение прежнее:
    компания по умолчанию, без отказа."""
    kz, uz = companies
    CompanyMembership.objects.create(user_id=active_user.id, company=kz, is_default=True)
    CompanyMembership.objects.create(user_id=active_user.id, company=uz)
    pair = issue_token_pair(active_user)

    resp = Client().post(f"{BASE}/token/refresh/", data={
        "refresh": pair["refresh"],
    }, content_type="application/json")

    assert resp.status_code == 200
    new_payload = decode_token(resp.json()["access"])
    assert new_payload.company == "htq-kz"
