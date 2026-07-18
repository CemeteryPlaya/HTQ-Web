"""Integration tests for user-service auth + profile flows."""

import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def seed_admin(session):
    """Create an active admin user with password 'admin123'."""
    from app.models.user import User, UserStatus
    from app.services.auth_service import hash_password

    user = User(
        username="admin",
        email="admin@test.local",
        password_hash=hash_password("admin123"),
        first_name="Admin",
        last_name="User",
        is_staff=True,
        is_superuser=True,
        status=UserStatus.ACTIVE,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


@pytest.mark.asyncio
async def test_token_obtain_pair_happy_path(client, seed_admin):
    resp = await client.post(
        "/api/users/v1/token/",
        json={"email": "admin@test.local", "password": "admin123"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "access" in data
    assert "refresh" in data
    assert data["token_type"] == "Bearer"


@pytest.mark.asyncio
async def test_token_wrong_password_returns_401(client, seed_admin):
    resp = await client.post(
        "/api/users/v1/token/",
        json={"email": "admin@test.local", "password": "wrong"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_token_unknown_user_returns_401(client):
    resp = await client.post(
        "/api/users/v1/token/",
        json={"email": "nobody@test.local", "password": "whatever"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_register_creates_pending_user(client):
    resp = await client.post(
        "/api/users/v1/register/",
        json={
            "email": "newuser@test.local",
            "password": "newpass123",
            "full_name": "New User",
        },
    )
    assert resp.status_code in (200, 201)


@pytest.mark.asyncio
async def test_profile_me_requires_auth(client):
    resp = await client.get("/api/users/v1/profile/me")
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_profile_me_with_token(client, seed_admin):
    token_resp = await client.post(
        "/api/users/v1/token/",
        json={"email": "admin@test.local", "password": "admin123"},
    )
    access = token_resp.json()["access"]
    resp = await client.get(
        "/api/users/v1/profile/me",
        headers={"Authorization": f"Bearer {access}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["email"] == "admin@test.local"


@pytest.mark.asyncio
async def test_change_password_with_correct_current(client, seed_admin):
    token_resp = await client.post(
        "/api/users/v1/token/",
        json={"email": "admin@test.local", "password": "admin123"},
    )
    access = token_resp.json()["access"]

    resp = await client.post(
        "/api/users/v1/profile/change-password",
        json={"current_password": "admin123", "new_password": "newpass456"},
        headers={"Authorization": f"Bearer {access}"},
    )
    assert resp.status_code in (200, 204)

    # Old password no longer valid
    fail = await client.post(
        "/api/users/v1/token/",
        json={"email": "admin@test.local", "password": "admin123"},
    )
    assert fail.status_code == 401

    # New password works
    ok = await client.post(
        "/api/users/v1/token/",
        json={"email": "admin@test.local", "password": "newpass456"},
    )
    assert ok.status_code == 200


@pytest.mark.asyncio
async def test_change_password_wrong_current_rejected(client, seed_admin):
    token_resp = await client.post(
        "/api/users/v1/token/",
        json={"email": "admin@test.local", "password": "admin123"},
    )
    access = token_resp.json()["access"]

    resp = await client.post(
        "/api/users/v1/profile/change-password",
        json={"current_password": "wrong", "new_password": "newpass456"},
        headers={"Authorization": f"Bearer {access}"},
    )
    assert resp.status_code == 400
