from tests.factories import auth


async def test_create_source_admin_only(client):
    r = await client.post(
        "/api/requests/v1/reference-sources/",
        json={"name": "Программы", "columns": ["admin", "budget"]}, headers=auth(1),
    )
    assert r.status_code == 403
    r = await client.post(
        "/api/requests/v1/reference-sources/",
        json={"name": "Программы", "columns": ["admin", "budget"]}, headers=auth(1, is_staff=True),
    )
    assert r.status_code == 201
    assert r.json()["columns"] == ["admin", "budget"]


async def test_rows_and_dependent_options(client):
    r = await client.post(
        "/api/requests/v1/reference-sources/",
        json={"name": "Ref", "columns": ["admin", "budget"]}, headers=auth(1, is_staff=True),
    )
    src = r.json()
    sid, slug = src["id"], src["slug"]

    for data in [{"admin": "A1", "budget": "B1"}, {"admin": "A1", "budget": "B2"}, {"admin": "A2", "budget": "B3"}]:
        rr = await client.post(f"/api/requests/v1/reference-sources/{sid}/rows/", json={"data": data}, headers=auth(1, is_staff=True))
        assert rr.status_code == 201

    r = await client.get(f"/api/requests/v1/reference-sources/{sid}/rows/", headers=auth(2))
    assert len(r.json()) == 3

    # distinct values of a column
    r = await client.get(f"/api/requests/v1/reference-sources/by-slug/{slug}/options", params={"column": "admin"}, headers=auth(2))
    assert sorted(r.json()["options"]) == ["A1", "A2"]

    # dependent select: budget where admin == A1
    r = await client.get(
        f"/api/requests/v1/reference-sources/by-slug/{slug}/options",
        params={"column": "budget", "filter_col": "admin", "filter_val": "A1"}, headers=auth(2),
    )
    assert sorted(r.json()["options"]) == ["B1", "B2"]


async def test_add_row_requires_admin(client):
    r = await client.post("/api/requests/v1/reference-sources/", json={"name": "Ref2", "columns": ["x"]}, headers=auth(1, is_staff=True))
    sid = r.json()["id"]
    r = await client.post(f"/api/requests/v1/reference-sources/{sid}/rows/", json={"data": {"x": "1"}}, headers=auth(2))
    assert r.status_code == 403
