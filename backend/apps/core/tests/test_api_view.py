import json

import jwt as pyjwt
import pytest
from django.conf import settings
from django.test import Client, RequestFactory
from pydantic import BaseModel

from htqweb.http import api_view


class EchoIn(BaseModel):
    title: str
    count: int = 1


@api_view(methods=("POST",), auth="jwt", body=EchoIn)
def echo(request, data: EchoIn):
    return {"title": data.title, "count": data.count,
            "user_id": request.token.user_id}


def _token(**over):
    claims = {"user_id": 7, "username": "t", "email": "t@htq.test",
              "is_staff": False, "is_superuser": False, "is_admin": False,
              "token_type": "access", "iat": 1, "exp": 9_999_999_999,
              "iss": "htqweb-auth", "sub": "7", **over}
    return pyjwt.encode(claims, settings.JWT_SECRET, algorithm="HS256")


def _post(body, token=None, path="/x/"):
    rf = RequestFactory()
    headers = {"HTTP_AUTHORIZATION": f"Bearer {token}"} if token else {}
    return echo(rf.post(path, data=json.dumps(body),
                        content_type="application/json", **headers))


def test_valid_request_passes_payload_and_body():
    resp = _post({"title": "hi"}, token=_token())
    assert resp.status_code == 200
    assert json.loads(resp.content) == {"title": "hi", "count": 1, "user_id": 7}


def test_missing_token_401_envelope():
    resp = _post({"title": "hi"})
    assert resp.status_code == 401
    assert "detail" in json.loads(resp.content)


def test_refresh_token_rejected():
    resp = _post({"title": "hi"}, token=_token(token_type="refresh"))
    assert resp.status_code == 401


def test_validation_error_422_envelope():
    resp = _post({"count": "not-an-int"}, token=_token())
    assert resp.status_code == 422
    assert "detail" in json.loads(resp.content)


def test_wrong_method_405():
    rf = RequestFactory()
    resp = echo(rf.get("/x/"))
    assert resp.status_code == 405


def test_request_id_middleware_echoes(client):
    resp = Client().get("/health/", HTTP_X_REQUEST_ID="req-123")
    assert resp["X-Request-ID"] == "req-123"


def test_malformed_claims_401_not_500():
    """A correctly-signed, correctly-issued token missing a required claim
    (user_id) must be rejected as 401, not surface pydantic.ValidationError
    as an unhandled 500. decode_token wraps PyJWT errors in AuthError but
    TokenPayload(**raw) construction sits outside that try/except, so both
    authenticators must also catch pydantic.ValidationError."""
    claims = {"username": "t", "email": "t@htq.test",
              "is_staff": False, "is_superuser": False, "is_admin": False,
              "token_type": "access", "iat": 1, "exp": 9_999_999_999,
              "iss": "htqweb-auth", "sub": "7"}
    token = pyjwt.encode(claims, settings.JWT_SECRET, algorithm="HS256")
    resp = _post({"title": "hi"}, token=token)
    assert resp.status_code == 401
    assert "detail" in json.loads(resp.content)
