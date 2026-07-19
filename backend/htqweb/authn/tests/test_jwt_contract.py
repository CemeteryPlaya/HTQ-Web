import jwt as pyjwt
import pytest
from django.conf import settings

from apps.users.models import User, UserStatus
from htqweb.authn.jwt import AuthError, decode_token, issue_token_pair

REQUIRED_CLAIMS = {"sub", "user_id", "username", "email", "is_staff",
                   "is_superuser", "is_admin", "token_type", "iat", "exp", "iss"}


@pytest.fixture
def user(db):
    return User.objects.create(username="jc", email="jc@htq.test",
                               password="x", is_staff=True,
                               status=UserStatus.ACTIVE)


def test_access_token_has_exact_platform_claims(user):
    pair = issue_token_pair(user)
    payload = pyjwt.decode(pair["access"], settings.JWT_SECRET,
                           algorithms=["HS256"], issuer="htqweb-auth")
    assert REQUIRED_CLAIMS <= set(payload)
    assert payload["iss"] == "htqweb-auth"
    assert payload["user_id"] == user.id
    assert payload["is_admin"] is True          # is_staff OR is_superuser
    assert payload["token_type"] == "access"
    assert pair["token_type"] == "Bearer"


def test_fastapi_issued_token_is_accepted(user):
    """Golden-тест сосуществования: токен в формате user-service валиден тут."""
    foreign = pyjwt.encode(
        {"sub": str(user.id), "user_id": user.id, "username": user.username,
         "email": user.email, "is_staff": True, "is_superuser": False,
         "is_admin": True, "token_type": "access",
         "iat": 1_700_000_000, "exp": 9_999_999_999, "iss": "htqweb-auth"},
        settings.JWT_SECRET, algorithm="HS256")
    payload = decode_token(foreign)
    assert payload.user_id == user.id
    assert payload.is_elevated is True


def test_wrong_issuer_rejected(user):
    bad = pyjwt.encode({"user_id": user.id, "exp": 9_999_999_999,
                        "iss": "user-service"},   # частая ошибка из CLAUDE.md
                       settings.JWT_SECRET, algorithm="HS256")
    with pytest.raises(AuthError):
        decode_token(bad)


def test_refresh_token_has_minimal_claims_only(user):
    """Ревью-фикс: refresh — 7-дневный токен, не должен нести привилегии/PII
    (см. services/user/app/services/auth_service.py::create_token_pair —
    refresh_payload там тоже содержит только user_id/token_type/iat/exp/iss).
    Привилегии переисчисляются из БД на каждый token/refresh/."""
    pair = issue_token_pair(user)
    payload = pyjwt.decode(pair["refresh"], settings.JWT_SECRET,
                           algorithms=["HS256"], issuer="htqweb-auth")
    assert payload["user_id"] == user.id
    assert payload["token_type"] == "refresh"
    assert payload["sub"] == str(user.id)
    assert "iat" in payload and "exp" in payload and payload["iss"] == "htqweb-auth"
    for field in ("username", "email", "is_staff", "is_superuser", "is_admin"):
        assert field not in payload
