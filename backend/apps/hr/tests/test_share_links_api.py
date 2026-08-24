"""Контракт /api/hr/v1/share-links/* + /public/{org,employee}/{token} —
паритет с services/hr/app/api/v1/share_links.py + app/api/public/{org,employee}.py
+ app/services/share_link_service.py.

Провенанс форм ответов: LinkOut/LinkCreatedOut/AuditEntryOut (объявлены
inline в share_links.py — нет отдельного schemas-модуля).

Зафиксированные ловушки паритета (проверяются тестами ниже):
  * POST возвращает raw token + url РОВНО один раз; GET-список/detail НИКОГДА
    token не несут; в БД лежит только SHA-256(token) (token_hash), не raw;
  * target_type='employee' без target_employee_id -> 422;
  * one_time-ссылка: второй consume после первого -> 410 (already used);
  * revoked/expired -> 410 с соответствующим detail;
  * публичные /public/org/{token} и /public/employee/{token} — БЕЗ JWT
    (auth=None), доступ по токену ссылки;
  * DELETE идемпотентен (повторный revoke не 404, не 500);
  * GET /{id}/audit — owner-only (чужая ссылка -> 404 "Link not found",
    не 403 — не раскрываем существование чужой ссылки).

Странность источника, сознательно НЕ портируемая (см. отчёт): slowapi
10/минуту rate-limit на публичных эндпойнтах — в кодовой базе Django-порта
нет rate-limiting инфраструктуры вообще (ни один существующий эндпойнт её не
использует) — тот же класс решений, что дропнутый dramatiq (Р2).

План: docs/plans/2026-07-20-hr-domain.md
"""
from __future__ import annotations

import datetime

import pytest
from django.db import connection
from django.test import Client

from apps.hr.models import Department, Employee, Position, ReportingRelation, ShareableLink, ShareLinkAudit
from apps.users.models import User, UserStatus
from htqweb.authn.jwt import issue_token_pair

BASE = "/api/hr/v1/share-links"
PUBLIC_ORG = "/api/hr/v1/public/org"
PUBLIC_EMPLOYEE = "/api/hr/v1/public/employee"


def _cols(table: str) -> dict:
    with connection.cursor() as cur:
        cur.execute(
            "SELECT column_name, is_nullable, column_default "
            "FROM information_schema.columns WHERE table_name = %s",
            [table],
        )
        return {r[0]: {"nullable": r[1] == "YES", "default": r[2]} for r in cur.fetchall()}


def _indexed_columns(table: str) -> set[str]:
    with connection.cursor() as cur:
        cur.execute("SELECT indexdef FROM pg_indexes WHERE tablename = %s", [table])
        defs = [r[0] for r in cur.fetchall()]
    cols: set[str] = set()
    for d in defs:
        inner = d[d.rfind("(") + 1 : d.rfind(")")]
        for part in inner.split(","):
            token = part.strip().strip('"').split()[0]
            cols.add(token.strip('"'))
    return cols


def _user_auth(username: str, *, is_staff=False):
    user = User.objects.create(
        username=username, email=f"{username}@htq.test", password="x",
        status=UserStatus.ACTIVE, is_staff=is_staff,
    )
    user.set_password("S3cret!Pass1")
    user.save()
    return user, {"HTTP_AUTHORIZATION": f"Bearer {issue_token_pair(user)['access']}"}


def _dep(name, path, **kw):
    return Department.objects.create(name=name, path=path, **kw)


def _pos(title, dep, weight, **kw):
    return Position.objects.create(title=title, department=dep, weight=weight, **kw)


def _emp(dep, pos, email, **kw):
    return Employee.objects.create(
        first_name="И", last_name="И", email=email, department=dep, position=pos,
        hire_date=datetime.date(2024, 1, 9), **kw,
    )


@pytest.fixture
def auth(db):
    _user, headers = _user_auth("linkowner")
    return headers


@pytest.fixture
def other_auth(db):
    _user, headers = _user_auth("otherowner")
    return headers


# ── schema паритет ───────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_shareable_link_columns_and_indexes():
    cols = _cols("hr_shareablelink")
    assert not cols["token_hash"]["nullable"]
    assert cols["token"]["nullable"]
    assert cols["expires_at"]["nullable"]
    assert cols["max_level"]["default"] is not None
    assert cols["is_active"]["default"] is not None
    assert "created_at" in cols
    assert "updated_at" not in cols  # D5-подобное решение: нет updated_at
    assert {"token_hash", "created_by_user_id", "is_active", "target_employee_id"} <= _indexed_columns(
        "hr_shareablelink"
    )


@pytest.mark.django_db
def test_share_link_audit_columns_and_indexes():
    cols = _cols("hr_sharelinkaudit")
    assert not cols["action"]["nullable"]
    assert cols["ip"]["nullable"]
    assert cols["reason"]["nullable"]
    assert "created_at" not in cols
    assert "occurred_at" in cols
    assert {"link_id", "occurred_at"} <= _indexed_columns("hr_sharelinkaudit")


@pytest.mark.django_db
def test_target_consistency_constraint_enforced():
    from django.db.utils import IntegrityError

    with pytest.raises(IntegrityError):
        ShareableLink.objects.create(
            token_hash="x" * 64, created_by_user_id=1,
            target_type="employee", target_employee_id=None,
        )


# ── auth ────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_requires_jwt():
    assert Client().get(f"{BASE}/").status_code == 401
    assert Client().post(f"{BASE}/", data={}, content_type="application/json").status_code == 401


# ── POST / ──────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_create_returns_token_and_url_exactly_once(auth):
    resp = Client().post(
        f"{BASE}/", data={"label": "Q1 chart"}, content_type="application/json", **auth,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert "token" in body and body["token"]
    assert body["url"].endswith(f"/public/org/{body['token']}")
    assert body["label"] == "Q1 chart"
    assert body["link_type"] == "one_time"
    assert body["target_type"] == "org"

    link = ShareableLink.objects.get(id=body["id"])
    assert link.token is None
    assert link.token_hash != body["token"]
    assert len(link.token_hash) == 64  # sha256 hex


@pytest.mark.django_db
def test_create_employee_target_requires_target_employee_id(auth):
    resp = Client().post(
        f"{BASE}/", data={"target_type": "employee"}, content_type="application/json", **auth,
    )
    assert resp.status_code == 422


@pytest.mark.django_db
def test_create_employee_target_url_points_at_employee_path(auth):
    dep = _dep("ИТ", "it")
    pos = _pos("Инженер", dep, weight=50)
    emp = _emp(dep, pos, "a@htq.test")
    resp = Client().post(
        f"{BASE}/",
        data={"target_type": "employee", "target_employee_id": emp.id},
        content_type="application/json", **auth,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["target_employee_id"] == emp.id
    assert f"/public/employee/{body['token']}" in body["url"]


# ── GET / (list) ──────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_list_returns_only_own_links_no_token(auth, other_auth):
    Client().post(f"{BASE}/", data={"label": "mine"}, content_type="application/json", **auth)
    Client().post(f"{BASE}/", data={"label": "theirs"}, content_type="application/json", **other_auth)

    body = Client().get(f"{BASE}/", **auth).json()
    assert len(body) == 1
    assert body[0]["label"] == "mine"
    assert "token" not in body[0]
    assert "url" not in body[0]


# ── DELETE /{id} ────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_delete_revokes_and_is_idempotent(auth):
    created = Client().post(
        f"{BASE}/", data={"label": "x"}, content_type="application/json", **auth,
    ).json()
    link_id = created["id"]

    resp = Client().delete(f"{BASE}/{link_id}", **auth)
    assert resp.status_code == 204
    link = ShareableLink.objects.get(id=link_id)
    assert link.is_active is False
    assert link.revoked_at is not None

    # idempotent: revoking an already-revoked link is still a clean 204.
    resp2 = Client().delete(f"{BASE}/{link_id}", **auth)
    assert resp2.status_code == 204


@pytest.mark.django_db
def test_delete_someone_elses_link_404(auth, other_auth):
    created = Client().post(
        f"{BASE}/", data={"label": "x"}, content_type="application/json", **auth,
    ).json()
    resp = Client().delete(f"{BASE}/{created['id']}", **other_auth)
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Link not found"


# ── GET /{id}/audit ───────────────────────────────────────────────────────

@pytest.mark.django_db
def test_audit_owner_only(auth, other_auth):
    created = Client().post(
        f"{BASE}/", data={"label": "x"}, content_type="application/json", **auth,
    ).json()
    link_id = created["id"]

    body = Client().get(f"{BASE}/{link_id}/audit", **auth).json()
    assert [e["action"] for e in body] == ["created"]

    resp = Client().get(f"{BASE}/{link_id}/audit", **other_auth)
    assert resp.status_code == 404


# ── public consume: org ─────────────────────────────────────────────────────

@pytest.mark.django_db
def test_public_org_consume_no_auth_required(auth):
    _dep("ИТ", "it")
    created = Client().post(
        f"{BASE}/", data={"label": "x", "link_type": "permanent_with_expiry"},
        content_type="application/json", **auth,
    ).json()
    token = created["token"]

    resp = Client().get(f"{PUBLIC_ORG}/{token}")
    assert resp.status_code == 200
    body = resp.json()
    assert "tree" in body
    assert resp["X-Robots-Tag"] == "noindex, nofollow"


@pytest.mark.django_db
def test_public_org_tree_edges_do_not_carry_relation_id(auth):
    """relation_id адресует /org/relations, /org/employee-relations — ручки
    правки, к которым у анонимного зрителя ссылки нет доступа (auth="jwt").
    Belt-and-braces: _strip_public_pii режет relation_id на уровне схемы, а
    не полагается только на то, что снаружи никто не спросит. origin
    остаётся — он не адресует ничего и даёт тот же честный пунктир на
    угаданных связях."""
    dep = _dep("ИТ", "it")
    boss = _pos("Начальник", dep, weight=10)
    report = _pos("Подчинённый", dep, weight=20)
    _emp(dep, boss, "boss@htq.test")
    _emp(dep, report, "report@htq.test")
    ReportingRelation.objects.create(
        superior_position=boss, subordinate_position=report,
        relation_type="direct", effective_from=datetime.date(2024, 1, 1),
    )

    created = Client().post(
        f"{BASE}/", data={"label": "x", "link_type": "permanent_with_expiry"},
        content_type="application/json", **auth,
    ).json()
    token = created["token"]

    body = Client().get(f"{PUBLIC_ORG}/{token}").json()
    edges = body["tree"]["edges"]
    assert edges, "ожидалось хотя бы одно ребро в дереве"
    assert all("relation_id" not in e for e in edges)
    assert any(e.get("origin") == "position" for e in edges)


@pytest.mark.django_db
def test_public_org_one_time_link_used_once(auth):
    _dep("ИТ", "it")
    created = Client().post(
        f"{BASE}/", data={"label": "x", "link_type": "one_time"},
        content_type="application/json", **auth,
    ).json()
    token = created["token"]

    first = Client().get(f"{PUBLIC_ORG}/{token}")
    assert first.status_code == 200

    second = Client().get(f"{PUBLIC_ORG}/{token}")
    assert second.status_code == 410
    assert "already been used" in second.json()["detail"]


@pytest.mark.django_db
def test_public_org_revoked_link_410(auth):
    created = Client().post(
        f"{BASE}/", data={"label": "x"}, content_type="application/json", **auth,
    ).json()
    Client().delete(f"{BASE}/{created['id']}", **auth)

    resp = Client().get(f"{PUBLIC_ORG}/{created['token']}")
    assert resp.status_code == 410
    assert "revoked" in resp.json()["detail"]


@pytest.mark.django_db
def test_public_org_unknown_token_404():
    resp = Client().get(f"{PUBLIC_ORG}/not-a-real-token")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_public_org_expired_link_410(auth):
    created = Client().post(
        f"{BASE}/",
        data={
            "label": "x", "link_type": "permanent_with_expiry",
            "expires_at": "2000-01-01T00:00:00Z",
        },
        content_type="application/json", **auth,
    ).json()

    resp = Client().get(f"{PUBLIC_ORG}/{created['token']}")
    assert resp.status_code == 410
    assert "expired" in resp.json()["detail"]


@pytest.mark.django_db
def test_public_org_employee_link_not_consumable_at_org_endpoint(auth):
    dep = _dep("ИТ", "it")
    pos = _pos("Инженер", dep, weight=50)
    emp = _emp(dep, pos, "a@htq.test")
    created = Client().post(
        f"{BASE}/",
        data={"target_type": "employee", "target_employee_id": emp.id},
        content_type="application/json", **auth,
    ).json()

    resp = Client().get(f"{PUBLIC_ORG}/{created['token']}")
    assert resp.status_code == 404


# ── public consume: employee ─────────────────────────────────────────────────

@pytest.mark.django_db
def test_public_employee_consume_returns_card(auth):
    dep = _dep("ИТ", "it")
    pos = _pos("Инженер", dep, weight=50)
    emp = _emp(dep, pos, "a@htq.test")
    created = Client().post(
        f"{BASE}/",
        data={"target_type": "employee", "target_employee_id": emp.id, "link_type": "permanent_with_expiry"},
        content_type="application/json", **auth,
    ).json()

    resp = Client().get(f"{PUBLIC_EMPLOYEE}/{created['token']}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["card"]["id"] == emp.id
    assert body["card"]["email"] is None  # public mode strips PII


@pytest.mark.django_db
def test_public_employee_org_link_not_consumable_at_employee_endpoint(auth):
    _dep("ИТ", "it")
    created = Client().post(
        f"{BASE}/", data={"label": "x"}, content_type="application/json", **auth,
    ).json()

    resp = Client().get(f"{PUBLIC_EMPLOYEE}/{created['token']}")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_public_employee_deleted_employee_gives_410(auth):
    dep = _dep("ИТ", "it")
    pos = _pos("Инженер", dep, weight=50)
    emp = _emp(dep, pos, "a@htq.test")
    created = Client().post(
        f"{BASE}/",
        data={"target_type": "employee", "target_employee_id": emp.id, "link_type": "permanent_with_expiry"},
        content_type="application/json", **auth,
    ).json()
    emp.is_deleted = True
    emp.save(update_fields=["is_deleted"])

    resp = Client().get(f"{PUBLIC_EMPLOYEE}/{created['token']}")
    assert resp.status_code == 410


# ── audit trail rows written on every consume/deny ──────────────────────────

@pytest.mark.django_db
def test_public_consume_writes_audit_row(auth):
    _dep("ИТ", "it")
    created = Client().post(
        f"{BASE}/", data={"label": "x", "link_type": "permanent_with_expiry"},
        content_type="application/json", **auth,
    ).json()
    Client().get(f"{PUBLIC_ORG}/{created['token']}")

    actions = list(
        ShareLinkAudit.objects.filter(link_id=created["id"]).values_list("action", flat=True)
    )
    assert "created" in actions
    assert "open" in actions
