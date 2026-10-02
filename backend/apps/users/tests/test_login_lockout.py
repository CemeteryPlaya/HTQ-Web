"""Блокировка входа через ``POST token/`` (D-S7-3): 5 неудач → 429 на 15 минут."""
import pytest
from django.core.management import call_command
from django.test import Client
from prometheus_client import REGISTRY

from apps.users.models import User, UserStatus
from apps.users.services import admin_service, profile_service
from htqweb import ratelimit
from htqweb.authn.jwt import issue_token_pair

BASE = "/api/users/v1"
GOOD = "Good1!Pass"


@pytest.fixture(autouse=True)
def lockout(settings):
    settings.AUTH_LOCKOUT_THRESHOLD = 5
    settings.AUTH_LOCKOUT_SECONDS = 900


@pytest.fixture
def alice(db):
    u = User.objects.create(username="alice", email="alice@htq.test", password="x",
                            status=UserStatus.ACTIVE)
    u.set_password(GOOD)
    u.save()
    return u


def _metric(reason):
    return REGISTRY.get_sample_value("htqweb_auth_lockout_total", {"reason": reason}) or 0.0


def _login(login, pw):
    return Client().post(f"{BASE}/token/", data={"email": login, "password": pw},
                         content_type="application/json")


def _fail_n(login, n):
    for _ in range(n):
        assert _login(login, "wrong").status_code == 401


def test_sixth_attempt_is_429_even_with_correct_password(alice, monkeypatch):
    monkeypatch.setattr("time.time", lambda: 1_800_000_000.0)  # Retry-After — от часов
    locked0, rejected0 = _metric("locked"), _metric("rejected")
    _fail_n("alice", 5)
    assert _metric("locked") == locked0 + 1
    resp = _login("alice", GOOD)
    assert _metric("rejected") == rejected0 + 1
    assert resp.status_code == 429
    body = resp.json()
    assert body["code"] == "E-AUTH-LOCKED"
    assert body["detail"]
    assert resp["Retry-After"] == "900"


def test_unknown_login_is_locked_the_same_way(db):
    _fail_n("nobody@htq.test", 5)
    assert _login("nobody@htq.test", "x").status_code == 429


def test_responses_do_not_reveal_existence(alice, monkeypatch):
    # Retry-After считается от часов — закрепляем, чтобы заголовки сравнивались.
    monkeypatch.setattr("time.time", lambda: 1_800_000_000.0)
    User.objects.create(username="pending3", email="pending3@htq.test", password="x",
                        status=UserStatus.PENDING)
    logins = ("ghost@htq.test", "pending3@htq.test", "alice@htq.test")

    def same(responses):
        assert len({r.status_code for r in responses}) == 1
        assert len({r.content for r in responses}) == 1
        heads = [{k: v for k, v in r.headers.items() if k.lower() not in ("content-length", "x-request-id")}
                 for r in responses]
        assert heads[0] == heads[1] == heads[2]

    first = [_login(x, "nope") for x in logins]
    assert first[0].status_code == 401
    same(first)
    for login in logins:
        _fail_n(login, 3)  # с первой попыткой выше — по 4 неудачи
    same([_login(x, "nope") for x in logins])  # пятая неудача
    locked = [_login(x, "nope") for x in logins]
    assert locked[0].status_code == 429
    same(locked)


def test_correct_password_of_inactive_account_still_says_not_activated(db):
    u = User.objects.create(username="pending4", email="pending4@htq.test", password="x",
                            status=UserStatus.PENDING)
    u.set_password(GOOD)
    u.save()
    resp = _login("pending4@htq.test", GOOD)
    assert resp.status_code == 401
    assert resp.json() == {"detail": "Account is not activated"}


def test_not_activated_answer_does_not_count_as_failure(db):
    u = User.objects.create(username="pending5", email="pending5@htq.test", password="x",
                            status=UserStatus.PENDING)
    u.set_password(GOOD)
    u.save()
    for _ in range(8):
        assert _login("pending5@htq.test", GOOD).status_code == 401
    assert ratelimit.login_locked("pending5@htq.test") is None
    assert _login("pending5@htq.test", GOOD).json() == {"detail": "Account is not activated"}


def test_username_case_differs_email_case_does_not(alice):
    other = User.objects.create(username="Alice", email="alice2@htq.test", password="x",
                                status=UserStatus.ACTIVE)
    other.set_password("Other1!Pass")
    other.save()
    _fail_n("Alice", 5)
    assert _login("Alice", "Other1!Pass").status_code == 429
    assert _login("alice", GOOD).status_code == 200
    _fail_n("Alice2@HTQ.test", 5)
    assert _login("alice2@htq.test", "Other1!Pass").status_code == 429


def test_success_resets_counter(alice):
    _fail_n("alice", 4)
    assert _login("alice", GOOD).status_code == 200
    _fail_n("alice", 4)
    assert _login("alice", GOOD).status_code == 200


def test_window_expires(alice, monkeypatch):
    now = {"t": 1_800_000_000.0}
    monkeypatch.setattr("time.time", lambda: now["t"])
    _fail_n("alice", 5)
    assert _login("alice", GOOD).status_code == 429
    now["t"] += 901
    assert _login("alice", GOOD).status_code == 200


def test_auth_unlock_command_unlocks(alice):
    _fail_n("alice", 5)
    call_command("auth_unlock", "alice@htq.test")
    assert _login("alice", GOOD).status_code == 200


def test_auth_unlock_unknown_login_is_harmless(db):
    _fail_n("ghost", 5)
    call_command("auth_unlock", "ghost")
    assert _login("ghost", "x").status_code == 401


def test_own_password_change_unlocks(alice):
    _fail_n("alice", 5)
    profile_service.change_password(alice, new_password="New1!Pass", current_password=GOOD)
    assert _login("alice", "New1!Pass").status_code == 200


def test_admin_set_password_unlocks(alice):
    _fail_n("alice@htq.test", 5)
    admin_service.set_password(alice, new_password="New1!Pass")
    assert _login("alice@htq.test", "New1!Pass").status_code == 200


def test_refresh_works_while_login_is_locked(alice):
    tokens = issue_token_pair(alice, company_slug=None)
    _fail_n("alice", 5)
    resp = Client().post(f"{BASE}/token/refresh/", data={"refresh": tokens["refresh"]},
                         content_type="application/json")
    assert resp.status_code == 200


def test_dead_cache_login_still_works_with_fallback(alice, monkeypatch, fallback_log_mode,
                                                    caplog):
    class Dead:
        def __getattr__(self, name):
            return lambda *a, **kw: None

    monkeypatch.setattr(ratelimit, "cache", Dead())
    with caplog.at_level("WARNING", logger="htqweb.fallback"):
        assert _login("alice", "wrong").status_code == 401
        assert _login("alice", GOOD).status_code == 200
    assert "htqweb.ratelimit.store_unavailable" in caplog.text


def test_threshold_zero_never_locks(settings, alice):
    settings.AUTH_LOCKOUT_THRESHOLD = 0
    _fail_n("alice", 12)
    assert _login("alice", GOOD).status_code == 200


def test_locked_log_line_has_no_login(alice, caplog):
    _fail_n("alice", 5)
    with caplog.at_level("WARNING", logger="apps.users.views"):
        _login("alice", GOOD)
    lines = [r.getMessage() for r in caplog.records if "auth_login_locked" in r.getMessage()]
    assert lines and "alice" not in lines[0]


def test_failure_and_locked_lines_share_the_key_and_use_real_ip(alice, caplog):
    with caplog.at_level("WARNING", logger="apps.users.views"):
        for _ in range(5):
            Client().post(f"{BASE}/token/", data={"email": "alice", "password": "wrong"},
                          content_type="application/json",
                          HTTP_X_REAL_IP="203.0.113.7", HTTP_X_FORWARDED_FOR="6.6.6.6, 203.0.113.7")
        Client().post(f"{BASE}/token/", data={"email": "alice", "password": GOOD},
                      content_type="application/json", HTTP_X_REAL_IP="203.0.113.7")
    msgs = [r.getMessage() for r in caplog.records]
    failed = [m for m in msgs if "auth_login_failed" in m]
    locked = [m for m in msgs if "auth_login_locked" in m]
    key = f"key={ratelimit.digest_prefix('alice')}"
    assert len(failed) == 5 and locked
    assert all(key in m and "ip=203.0.113.7" in m for m in failed + locked)
    assert not any("6.6.6.6" in m or "alice" in m for m in msgs)
