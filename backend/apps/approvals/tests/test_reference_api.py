"""Contract tests for ``/api/requests/v1/reference-sources/*``.

Source: ``services/requests/app/api/v1/reference.py`` +
``services/requests/tests/{test_reference_api,test_data_table_access}.py``.
Management (create/update/delete a source, add/remove rows) is
platform-admin only (``is_elevated`` -- the same predicate the FastAPI
original's ``_require_admin`` checks); reads of a source's metadata/rows and
``options`` require only authentication. A template's auto-maintained data
table (``template_id`` set) additionally gates ``rows`` reads and
``my-data-tables``/``access`` through
``template_data_table.can_view_/can_manage_data_table`` -- see
``test_forms_api.py`` for that side's template lifecycle coverage.
"""

import pytest
from django.test import Client

from apps.approvals.models import RequestReferenceRow, RequestReferenceSource

from .helpers import BASE, admin_token, auth, patch_json, post_json, simple_workflow, token

_SCHEMA = {"fields": [{"type": "text", "key": "x", "label": "X"}]}


# ── list / create ───────────────────────────────────────────────────────

@pytest.mark.django_db
def test_sources_require_auth():
    assert Client().get(f"{BASE}/reference-sources/").status_code == 401


@pytest.mark.django_db
def test_create_source_admin_only():
    resp = post_json(Client(), f"{BASE}/reference-sources/",
                     {"name": "Программы", "columns": ["admin", "budget"]}, **auth())
    assert resp.status_code == 403

    resp = post_json(Client(), f"{BASE}/reference-sources/",
                     {"name": "Программы", "columns": ["admin", "budget"]},
                     **auth(admin_token()))
    assert resp.status_code == 201
    assert resp.json()["columns"] == ["admin", "budget"]


@pytest.mark.django_db
def test_create_source_duplicate_slug_conflicts():
    post_json(Client(), f"{BASE}/reference-sources/",
             {"name": "Ref"}, **auth(admin_token()))
    resp = post_json(Client(), f"{BASE}/reference-sources/",
                     {"name": "Ref"}, **auth(admin_token()))
    assert resp.status_code == 409


@pytest.mark.django_db
def test_list_sources_orders_by_name():
    post_json(Client(), f"{BASE}/reference-sources/", {"name": "Zeta"}, **auth(admin_token()))
    post_json(Client(), f"{BASE}/reference-sources/", {"name": "Alpha"}, **auth(admin_token()))
    resp = Client().get(f"{BASE}/reference-sources/", **auth())
    assert resp.status_code == 200
    names = [s["name"] for s in resp.json()]
    assert names == sorted(names)
    assert "Alpha" in names and "Zeta" in names


# ── get / update / delete ────────────────────────────────────────────────

@pytest.mark.django_db
def test_get_source_404():
    assert Client().get(f"{BASE}/reference-sources/999/", **auth()).status_code == 404


@pytest.mark.django_db
def test_get_source_any_authenticated_user():
    src = RequestReferenceSource.objects.create(slug="s1", name="S1", columns_json=["a"])
    resp = Client().get(f"{BASE}/reference-sources/{src.id}/", **auth())
    assert resp.status_code == 200
    assert resp.json()["slug"] == "s1"


@pytest.mark.django_db
def test_update_source_admin_only():
    src = RequestReferenceSource.objects.create(slug="s2", name="S2", columns_json=["a"])
    resp = patch_json(Client(), f"{BASE}/reference-sources/{src.id}/",
                      {"name": "S2b"}, **auth())
    assert resp.status_code == 403

    resp = patch_json(Client(), f"{BASE}/reference-sources/{src.id}/",
                      {"name": "S2b", "columns": ["a", "b"]}, **auth(admin_token()))
    assert resp.status_code == 200
    assert resp.json()["name"] == "S2b"
    assert resp.json()["columns"] == ["a", "b"]


@pytest.mark.django_db
def test_delete_source_admin_only():
    src = RequestReferenceSource.objects.create(slug="s3", name="S3")
    resp = Client().delete(f"{BASE}/reference-sources/{src.id}/", **auth())
    assert resp.status_code == 403

    resp = Client().delete(f"{BASE}/reference-sources/{src.id}/", **auth(admin_token()))
    assert resp.status_code == 204
    assert not RequestReferenceSource.objects.filter(pk=src.id).exists()


# ── rows + by-slug options (mirrors test_reference_api.py) ──────────────

@pytest.mark.django_db
def test_rows_and_dependent_options():
    client = Client()
    resp = post_json(client, f"{BASE}/reference-sources/",
                     {"name": "Ref", "columns": ["admin", "budget"]},
                     **auth(admin_token()))
    src = resp.json()
    sid, slug = src["id"], src["slug"]

    for data in [{"admin": "A1", "budget": "B1"}, {"admin": "A1", "budget": "B2"},
                 {"admin": "A2", "budget": "B3"}]:
        rr = post_json(client, f"{BASE}/reference-sources/{sid}/rows/",
                       {"data": data}, **auth(admin_token()))
        assert rr.status_code == 201

    resp = client.get(f"{BASE}/reference-sources/{sid}/rows/", **auth())
    assert len(resp.json()) == 3

    resp = client.get(f"{BASE}/reference-sources/by-slug/{slug}/options",
                      {"column": "admin"}, **auth())
    assert sorted(resp.json()["options"]) == ["A1", "A2"]

    resp = client.get(f"{BASE}/reference-sources/by-slug/{slug}/options",
                      {"column": "budget", "filter_col": "admin", "filter_val": "A1"},
                      **auth())
    assert sorted(resp.json()["options"]) == ["B1", "B2"]


@pytest.mark.django_db
def test_add_row_requires_admin():
    resp = post_json(Client(), f"{BASE}/reference-sources/",
                     {"name": "Ref2", "columns": ["x"]}, **auth(admin_token()))
    sid = resp.json()["id"]
    resp = post_json(Client(), f"{BASE}/reference-sources/{sid}/rows/",
                     {"data": {"x": "1"}}, **auth())
    assert resp.status_code == 403


@pytest.mark.django_db
def test_delete_row_admin_only_and_404_wrong_source():
    client = Client()
    src1 = RequestReferenceSource.objects.create(slug="rs1", name="RS1")
    src2 = RequestReferenceSource.objects.create(slug="rs2", name="RS2")
    row = RequestReferenceRow.objects.create(source=src1, data_json={"x": 1})

    resp = client.delete(f"{BASE}/reference-sources/{src1.id}/rows/{row.id}/", **auth())
    assert resp.status_code == 403

    # wrong source_id in the path -> 404, even for an admin
    resp = client.delete(f"{BASE}/reference-sources/{src2.id}/rows/{row.id}/",
                         **auth(admin_token()))
    assert resp.status_code == 404
    assert RequestReferenceRow.objects.filter(pk=row.id).exists()

    resp = client.delete(f"{BASE}/reference-sources/{src1.id}/rows/{row.id}/",
                         **auth(admin_token()))
    assert resp.status_code == 204
    assert not RequestReferenceRow.objects.filter(pk=row.id).exists()


@pytest.mark.django_db
def test_options_requires_column_param():
    RequestReferenceSource.objects.create(slug="optslug", name="Opt")
    resp = Client().get(f"{BASE}/reference-sources/by-slug/optslug/options", **auth())
    assert resp.status_code == 422


@pytest.mark.django_db
def test_options_404_unknown_slug():
    resp = Client().get(f"{BASE}/reference-sources/by-slug/ghost/options",
                        {"column": "x"}, **auth())
    assert resp.status_code == 404


# ── template data tables: my-data-tables / access (mirrors
#    test_data_table_access.py) ───────────────────────────────────────────

def _make_table(client: Client):
    tid = post_json(client, f"{BASE}/templates/", {"name": "AccT"},
                    **auth(admin_token())).json()["id"]
    post_json(client, f"{BASE}/templates/{tid}/versions/",
             {"schema_json": _SCHEMA, "workflow_json": simple_workflow()},
             **auth(admin_token()))
    resp = client.get(f"{BASE}/reference-sources/my-data-tables", **auth(admin_token()))
    sid = next(s["id"] for s in resp.json() if s["template_id"] == tid)
    return tid, sid


@pytest.mark.django_db
def test_stranger_cannot_see_or_read_data_table():
    client = Client()
    _, sid = _make_table(client)
    resp = client.get(f"{BASE}/reference-sources/my-data-tables", **auth(token(user_id=77, sub="77")))
    assert all(s["id"] != sid for s in resp.json())
    resp = client.get(f"{BASE}/reference-sources/{sid}/rows/",
                      **auth(token(user_id=77, sub="77")))
    assert resp.status_code == 403


@pytest.mark.django_db
def test_grant_access_lets_viewer_read_data_table():
    client = Client()
    _, sid = _make_table(client)
    resp = patch_json(client, f"{BASE}/reference-sources/{sid}/access",
                      {"viewer_ids": [5]}, **auth(admin_token()))
    assert resp.status_code == 200

    viewer = token(user_id=5, sub="5")
    resp = client.get(f"{BASE}/reference-sources/my-data-tables", **auth(viewer))
    tbl = next((s for s in resp.json() if s["id"] == sid), None)
    assert tbl is not None and tbl["can_manage"] is False

    resp = client.get(f"{BASE}/reference-sources/{sid}/rows/", **auth(viewer))
    assert resp.status_code == 200


@pytest.mark.django_db
def test_viewer_cannot_manage_access():
    client = Client()
    _, sid = _make_table(client)
    patch_json(client, f"{BASE}/reference-sources/{sid}/access",
              {"viewer_ids": [5]}, **auth(admin_token()))
    resp = patch_json(client, f"{BASE}/reference-sources/{sid}/access",
                      {"viewer_ids": [5, 6]}, **auth(token(user_id=5, sub="5")))
    assert resp.status_code == 403


@pytest.mark.django_db
def test_set_access_400_when_not_a_template_table():
    src = RequestReferenceSource.objects.create(slug="manual1", name="Manual")
    resp = patch_json(Client(), f"{BASE}/reference-sources/{src.id}/access",
                      {"viewer_ids": [5]}, **auth(admin_token()))
    assert resp.status_code == 400


@pytest.mark.django_db
def test_set_access_404_unknown_source():
    resp = patch_json(Client(), f"{BASE}/reference-sources/999/access",
                      {"viewer_ids": [5]}, **auth(admin_token()))
    assert resp.status_code == 404
