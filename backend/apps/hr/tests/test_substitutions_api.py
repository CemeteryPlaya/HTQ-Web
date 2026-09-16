"""HTTP матрицы замещения.

Права — как у остальных мутаций должности: читать может любой
аутентифицированный, править только платформенный администратор. Матрица
утверждается приказом ГД, и правка её каждым кадровиком противоречила бы
самому документу.
"""
from __future__ import annotations

import datetime as dt

import pytest
from django.test import Client

from apps.hr.models import Department, Position, SubstitutionKind
from apps.hr.services import substitution_service as svc
from apps.users.models import User, UserStatus
from htqweb.authn.jwt import issue_token_pair

BASE = "/api/hr/v1"


@pytest.fixture
def auth(db):
    """Обычный вошедший пользователь — годится для reads, НЕ годится для writes."""
    user = User.objects.create(
        username="hr-user", email="hr-user@htq.test", password="x", status=UserStatus.ACTIVE,
    )
    user.set_password("S3cret!")
    user.save()
    return {"HTTP_AUTHORIZATION": f"Bearer {issue_token_pair(user)['access']}"}


@pytest.fixture
def admin_auth(db):
    """is_staff=True — elevated, требуется для writes (require_hr_write)."""
    user = User.objects.create(
        username="hr-admin", email="hr-admin@htq.test", password="x", status=UserStatus.ACTIVE,
        is_staff=True,
    )
    user.set_password("Adm1n!Pass")
    user.save()
    return {"HTTP_AUTHORIZATION": f"Bearer {issue_token_pair(user)['access']}"}


@pytest.fixture
def trio(db):
    dep = Department.objects.create(name="Руководство", path="upr")
    return {
        "ceo": Position.objects.create(title="Генеральный директор", department=dep, weight=10),
        "ops": Position.objects.create(title="Операционный директор", department=dep, weight=130),
        "cfo": Position.objects.create(title="Финансовый директор", department=dep, weight=110),
    }


def _body(trio, **over):
    body = {
        "substitute_position_id": trio["ops"].id,
        "kind": "primary",
        "basis": "Приказ ГД",
        "valid_from": "2026-01-01",
    }
    body.update(over)
    return body


@pytest.mark.django_db
def test_list_requires_jwt(trio):
    resp = Client().get(f"{BASE}/positions/{trio['ceo'].id}/substitutions")
    assert resp.status_code == 401


@pytest.mark.django_db
def test_create_requires_admin(trio, auth):
    resp = Client().post(f"{BASE}/positions/{trio['ceo'].id}/substitutions",
                         data=_body(trio), content_type="application/json", **auth)
    assert resp.status_code == 403


@pytest.mark.django_db
def test_create_then_list(trio, admin_auth, auth):
    created = Client().post(f"{BASE}/positions/{trio['ceo'].id}/substitutions",
                            data=_body(trio), content_type="application/json",
                            **admin_auth)
    assert created.status_code == 201
    body = created.json()
    assert body["substitute_position_title"] == "Операционный директор"
    assert {"id", "position_id", "substitute_position_id",
            "substitute_position_title", "kind", "basis", "note",
            "valid_from", "valid_to", "created_at", "updated_at"} == set(body)

    listed = Client().get(f"{BASE}/positions/{trio['ceo'].id}/substitutions", **auth)
    assert listed.status_code == 200
    assert [r["id"] for r in listed.json()] == [body["id"]]


@pytest.mark.django_db
def test_both_url_spellings_work(trio, auth):
    """APPEND_SLASH=False — обе формы обязаны быть зарегистрированы."""
    for url in (f"{BASE}/positions/{trio['ceo'].id}/substitutions",
                f"{BASE}/positions/{trio['ceo'].id}/substitutions/"):
        assert Client().get(url, **auth).status_code == 200


@pytest.mark.django_db
def test_self_substitution_is_422(trio, admin_auth):
    resp = Client().post(f"{BASE}/positions/{trio['ceo'].id}/substitutions",
                         data=_body(trio, substitute_position_id=trio["ceo"].id),
                         content_type="application/json", **admin_auth)
    assert resp.status_code == 422
    assert "сама себя" in resp.json()["detail"]


@pytest.mark.django_db
def test_overlap_is_409_and_says_what_to_do(trio, admin_auth):
    Client().post(f"{BASE}/positions/{trio['ceo'].id}/substitutions",
                  data=_body(trio), content_type="application/json", **admin_auth)
    resp = Client().post(f"{BASE}/positions/{trio['ceo'].id}/substitutions",
                         data=_body(trio, substitute_position_id=trio["cfo"].id,
                                    valid_from="2026-06-01"),
                         content_type="application/json", **admin_auth)
    assert resp.status_code == 409
    assert "датой окончания" in resp.json()["detail"]


@pytest.mark.django_db
def test_unknown_substitute_position_is_404(trio, admin_auth):
    resp = Client().post(f"{BASE}/positions/{trio['ceo'].id}/substitutions",
                         data=_body(trio, substitute_position_id=10_000_000),
                         content_type="application/json", **admin_auth)
    assert resp.status_code == 404


@pytest.mark.django_db
def test_patch_closes_the_period(trio, admin_auth):
    row = svc.create(position_id=trio["ceo"].id,
                     substitute_position_id=trio["ops"].id,
                     kind=SubstitutionKind.PRIMARY, basis="Приказ ГД", note=None,
                     valid_from=dt.date(2026, 1, 1), valid_to=None)
    resp = Client().patch(f"{BASE}/substitutions/{row.id}",
                          data={"valid_to": "2026-05-31"},
                          content_type="application/json", **admin_auth)
    assert resp.status_code == 200
    assert resp.json()["valid_to"] == "2026-05-31"


@pytest.mark.django_db
def test_delete_then_404(trio, admin_auth):
    row = svc.create(position_id=trio["ceo"].id,
                     substitute_position_id=trio["ops"].id,
                     kind=SubstitutionKind.PRIMARY, basis="Приказ ГД", note=None,
                     valid_from=dt.date(2026, 1, 1), valid_to=None)
    assert Client().delete(f"{BASE}/substitutions/{row.id}", **admin_auth).status_code == 204
    assert Client().delete(f"{BASE}/substitutions/{row.id}", **admin_auth).status_code == 404


@pytest.mark.django_db
def test_valid_to_before_valid_from_is_422(trio, admin_auth):
    resp = Client().post(f"{BASE}/positions/{trio['ceo'].id}/substitutions",
                         data=_body(trio, valid_from="2026-06-01", valid_to="2026-01-01"),
                         content_type="application/json", **admin_auth)
    assert resp.status_code == 422
