import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db import get_db_session
from app.main import app
from app.models import Base
from app.models.user_replica import RequestUser
from tests.factories import auth


@pytest.fixture
async def fk_client():
    """Client backed by a SQLite engine with FK enforcement ON.

    The default ``client`` fixture leaves SQLite foreign keys OFF, which hides
    the request_users FK from request_projects — exactly the constraint that
    fails on production Postgres. This fixture turns it on to reproduce that.
    """
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine.sync_engine, "connect")
    def _fk_pragma(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _override_db():
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db_session] = _override_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        ac._factory = factory  # expose for assertions
        yield ac
    app.dependency_overrides.clear()
    await engine.dispose()


async def test_create_self_heals_owner_replica(fk_client):
    """Creating a project as a user absent from request_users must succeed:
    the endpoint self-heals the owner's replica row (regression for the
    request_projects_owner_id_fkey ForeignKeyViolationError)."""
    r = await fk_client.post(
        "/api/requests/v1/projects/",
        json={"name": "Центральный Офис г.Тараз"},
        headers=auth(1, is_staff=True),
    )
    assert r.status_code == 201, r.text
    assert r.json()["owner_id"] == 1

    async with fk_client._factory() as session:
        owner = await session.get(RequestUser, 1)
        assert owner is not None
        assert owner.username == "user1"
        assert owner.is_elevated is True


async def test_create_requires_elevated(client):
    r = await client.post("/api/requests/v1/projects/", json={"name": "Alpha"}, headers=auth(1))
    assert r.status_code == 403
    r = await client.post("/api/requests/v1/projects/", json={"name": "Alpha"}, headers=auth(1, is_staff=True))
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "Alpha"
    assert body["owner_id"] == 1
    assert body["currency"] == "KZT"


async def test_list_and_get(client):
    await client.post("/api/requests/v1/projects/", json={"name": "Beta"}, headers=auth(1, is_staff=True))
    r = await client.get("/api/requests/v1/projects/", headers=auth(2))
    assert r.status_code == 200
    assert any(p["name"] == "Beta" for p in r.json())
    pid = r.json()[0]["id"]
    r2 = await client.get(f"/api/requests/v1/projects/{pid}/", headers=auth(2))
    assert r2.status_code == 200


async def test_get_missing_404(client):
    r = await client.get("/api/requests/v1/projects/999/", headers=auth(1, is_staff=True))
    assert r.status_code == 404


async def test_membership_flow_and_project_admin_can_update(client):
    r = await client.post("/api/requests/v1/projects/", json={"name": "Gamma"}, headers=auth(1, is_staff=True))
    pid = r.json()["id"]
    r = await client.post(
        f"/api/requests/v1/projects/{pid}/members/",
        json={"user_id": 7, "role": "admin"},
        headers=auth(1, is_staff=True),
    )
    assert r.status_code == 201
    r = await client.patch(
        f"/api/requests/v1/projects/{pid}/",
        json={"description": "updated by project admin"},
        headers=auth(7),
    )
    assert r.status_code == 200
    assert r.json()["description"] == "updated by project admin"
    r = await client.patch(
        f"/api/requests/v1/projects/{pid}/",
        json={"description": "nope"},
        headers=auth(8),
    )
    assert r.status_code == 403
    r = await client.get(f"/api/requests/v1/projects/{pid}/members/", headers=auth(1, is_staff=True))
    assert any(m["user_id"] == 7 and m["role"] == "admin" for m in r.json())
    r = await client.delete(f"/api/requests/v1/projects/{pid}/members/7/", headers=auth(1, is_staff=True))
    assert r.status_code == 204


async def test_delete_requires_elevated(client):
    r = await client.post("/api/requests/v1/projects/", json={"name": "Delta"}, headers=auth(1, is_staff=True))
    pid = r.json()["id"]
    assert (await client.delete(f"/api/requests/v1/projects/{pid}/", headers=auth(2))).status_code == 403
    assert (await client.delete(f"/api/requests/v1/projects/{pid}/", headers=auth(1, is_staff=True))).status_code == 204
