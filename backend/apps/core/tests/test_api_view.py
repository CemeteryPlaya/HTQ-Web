import json
from datetime import datetime, timezone
from decimal import Decimal

import jwt as pyjwt
import pytest
from django.conf import settings
from django.core.exceptions import PermissionDenied, SuspiciousOperation
from django.http import Http404, HttpResponse
from django.test import Client, RequestFactory
from pydantic import BaseModel

from apps.core.models import ServiceStatus
from htqweb.http import api_view


class EchoIn(BaseModel):
    title: str
    count: int = 1


@api_view(methods=("POST",), auth="jwt", body=EchoIn)
def echo(request, data: EchoIn):
    return {"title": data.title, "count": data.count,
            "user_id": request.token.user_id}


class EchoOut(BaseModel):
    title: str
    created_at: datetime
    amount: Decimal
    payload: bytes


@api_view(methods=("GET",), auth=None)
def model_view(request):
    return EchoOut(title="hi",
                   created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
                   amount=Decimal("12.50"),
                   payload=b"raw-bytes")


@api_view(methods=("GET",), auth=None)
def raw_response_view(request):
    return HttpResponse(b"raw", status=204)


class EchoListItem(BaseModel):
    id: int
    label: str


@api_view(methods=("GET",), auth=None)
def model_list_view(request):
    return [EchoListItem(id=1, label="a"), EchoListItem(id=2, label="b")]


@api_view(methods=("GET",), auth=None)
def empty_model_list_view(request):
    return []


@api_view(methods=("GET",), auth="admin_session")
def admin_only_view(request):
    return {"user_id": request.token.user_id}


@api_view(methods=("POST",), auth="jwt", admin=True)
def admin_gated_view(request):
    return {"ok": True}


@api_view(methods=("GET",), auth=None)
def no_auth_view(request):
    return {"token_is_none": request.token is None}


@api_view(methods=("GET",), auth=None)
def disabled_service_view(request):
    from apps.core.services import require_service
    require_service("hr")
    return {"ok": True}


@api_view(methods=("GET",), auth=None)
def http404_view(request):
    raise Http404("not here")


@api_view(methods=("GET",), auth=None)
def http404_no_message_view(request):
    raise Http404()


@api_view(methods=("GET",), auth=None)
def permission_denied_view(request):
    raise PermissionDenied("nope")


@api_view(methods=("GET",), auth=None)
def suspicious_operation_view(request):
    raise SuspiciousOperation("bad")


@api_view(methods=("POST",), auth=None, status=201)
def created_view(request):
    return {"created": True}


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
    assert "detail" in json.loads(resp.content)


def test_model_response_serialized_with_mode_json():
    """Guards `result.model_dump(mode="json")` in htqweb/http.py.

    datetime/Decimal alone don't prove this: DjangoJSONEncoder (JsonResponse's
    default encoder) serializes raw datetime/Decimal itself, so those fields
    pass identically under mode="python" too. `payload: bytes` is the field
    that actually bites: under mode="python" it stays a `bytes` instance
    inside the dumped dict, and neither `json.dumps` nor DjangoJSONEncoder can
    encode bytes -> the view raises and api_view's except turns it into a 500.
    Only mode="json" converts it to a plain str first, so this test fails
    without mode="json" and passes with it.
    """
    rf = RequestFactory()
    resp = model_view(rf.get("/model/"))
    assert resp.status_code == 200
    assert json.loads(resp.content) == {
        "title": "hi",
        "created_at": "2024-01-01T00:00:00Z",
        "amount": "12.50",
        "payload": "raw-bytes",
    }


def test_raw_http_response_passed_through_untouched():
    rf = RequestFactory()
    resp = raw_response_view(rf.get("/raw/"))
    assert resp.status_code == 204
    assert resp.content == b"raw"


def _admin_token(**over):
    claims = {"user_id": 9, "username": "a", "email": "a@htq.test",
              "is_staff": False, "is_superuser": False, "is_admin": False,
              "token_type": "access", "iat": 1, "exp": 9_999_999_999,
              "iss": "htqweb-auth", "sub": "9", **over}
    return pyjwt.encode(claims, settings.JWT_SECRET, algorithm="HS256")


def test_admin_session_elevated_authenticates():
    rf = RequestFactory()
    token = _admin_token(is_staff=True)
    resp = admin_only_view(rf.get("/admin-x/", HTTP_COOKIE=f"admin_session={token}"))
    assert resp.status_code == 200
    assert json.loads(resp.content) == {"user_id": 9}


def test_admin_session_non_elevated_401():
    rf = RequestFactory()
    token = _admin_token()  # is_admin/is_staff/is_superuser all false
    resp = admin_only_view(rf.get("/admin-x/", HTTP_COOKIE=f"admin_session={token}"))
    assert resp.status_code == 401
    assert "detail" in json.loads(resp.content)


def test_admin_session_missing_cookie_401():
    rf = RequestFactory()
    resp = admin_only_view(rf.get("/admin-x/"))
    assert resp.status_code == 401
    assert "detail" in json.loads(resp.content)


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


def test_no_auth_view_gets_token_none_not_attributeerror():
    """Finding 9: auth=None must set request.token = None, not leave it unset."""
    rf = RequestFactory()
    resp = no_auth_view(rf.get("/no-auth/"))
    assert resp.status_code == 200
    assert json.loads(resp.content) == {"token_is_none": True}


def test_admin_session_refresh_token_rejected():
    """Finding 4: admin_session must require token_type == 'access', not just
    is_elevated — otherwise a 7-day refresh token placed in the cookie
    authenticates as admin."""
    rf = RequestFactory()
    token = _admin_token(is_staff=True, token_type="refresh")
    resp = admin_only_view(rf.get("/admin-x/", HTTP_COOKIE=f"admin_session={token}"))
    assert resp.status_code == 401
    assert "detail" in json.loads(resp.content)


@pytest.mark.django_db
def test_require_service_disabled_returns_503_envelope():
    """Finding 1: ServiceDisabled raised inside a view body (require_service
    against a disabled neighbour app) must surface as the same 503 envelope
    the HTTP gate uses, not the generic 500 from api_view's blanket except."""
    ServiceStatus.objects.update_or_create(app_label="hr", defaults={"enabled": False})
    rf = RequestFactory()
    resp = disabled_service_view(rf.get("/disabled/"))
    assert resp.status_code == 503
    body = json.loads(resp.content)
    assert body["code"] == "service_disabled"
    assert body["service"] == "hr"
    assert "detail" in body


def test_http404_mapped_to_404_envelope():
    """Finding 4: a message passed to Http404() must surface as `detail`,
    not be discarded in favour of a generic 'Not Found'."""
    rf = RequestFactory()
    resp = http404_view(rf.get("/404/"))
    assert resp.status_code == 404
    assert json.loads(resp.content) == {"detail": "not here"}


def test_http404_without_message_falls_back_to_generic_detail():
    rf = RequestFactory()
    resp = http404_no_message_view(rf.get("/404-generic/"))
    assert resp.status_code == 404
    assert json.loads(resp.content) == {"detail": "Not Found"}


def test_list_of_basemodel_serialized_with_mode_json():
    """Finding 6: api_view must shape a `list[BaseModel]` return value the
    same way it shapes a single BaseModel — via `model_dump(mode="json")`
    on each item — not just pass it through the generic dict/list branch
    (which would leave BaseModel instances un-serialized)."""
    rf = RequestFactory()
    resp = model_list_view(rf.get("/model-list/"))
    assert resp.status_code == 200
    assert json.loads(resp.content) == [
        {"id": 1, "label": "a"},
        {"id": 2, "label": "b"},
    ]


def test_empty_list_response_still_returns_empty_json_array():
    rf = RequestFactory()
    resp = empty_model_list_view(rf.get("/model-list-empty/"))
    assert resp.status_code == 200
    assert json.loads(resp.content) == []


def test_permission_denied_mapped_to_403_envelope():
    rf = RequestFactory()
    resp = permission_denied_view(rf.get("/403/"))
    assert resp.status_code == 403
    assert json.loads(resp.content) == {"detail": "Forbidden"}


def test_suspicious_operation_mapped_to_400_envelope():
    rf = RequestFactory()
    resp = suspicious_operation_view(rf.get("/400/"))
    assert resp.status_code == 400
    assert json.loads(resp.content) == {"detail": "Bad Request"}


def test_custom_status_returned_with_body_intact():
    """Finding 3: api_view(status=201) must apply to dict/BaseModel bodies."""
    rf = RequestFactory()
    resp = created_view(rf.post("/created/"))
    assert resp.status_code == 201
    assert json.loads(resp.content) == {"created": True}


# ── R1: api_view(admin=True) — the single platform admin-gate seam ─────────


def test_admin_true_no_token_401_envelope():
    rf = RequestFactory()
    resp = admin_gated_view(rf.post("/admin-gated/"))
    assert resp.status_code == 401
    assert "detail" in json.loads(resp.content)


def test_admin_true_non_elevated_token_403_envelope():
    rf = RequestFactory()
    token = _token()  # is_staff/is_superuser/is_admin all False
    resp = admin_gated_view(
        rf.post("/admin-gated/", HTTP_AUTHORIZATION=f"Bearer {token}"),
    )
    assert resp.status_code == 403
    assert json.loads(resp.content) == {"detail": "Forbidden"}


def test_admin_true_elevated_token_200():
    rf = RequestFactory()
    token = _token(is_staff=True)
    resp = admin_gated_view(
        rf.post("/admin-gated/", HTTP_AUTHORIZATION=f"Bearer {token}"),
    )
    assert resp.status_code == 200
    assert json.loads(resp.content) == {"ok": True}


def test_admin_true_with_auth_none_raises_at_decoration_time():
    """admin=True only makes sense layered on top of an authenticator —
    auth=None never sets a real request.token, so there's nothing for the
    admin predicate to check. Catch that programming error eagerly, at
    decoration time, not as a confusing AttributeError/403 at request time."""
    with pytest.raises(ValueError):
        @api_view(methods=("GET",), auth=None, admin=True)
        def _bad_view(request):
            return {"unreachable": True}
