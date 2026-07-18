"""Integration tests for Contact Requests API endpoints."""

import pytest

from tests.conftest import admin_headers


@pytest.mark.asyncio
async def test_create_contact_request_public(client):
    resp = await client.post(
        "/api/cms/v1/contact-requests/",
        json={
            "first_name": "John",
            "last_name": "Doe",
            "email": "john@example.com",
            "message": "Hello, I have a question.",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["email"] == "john@example.com"
    assert data["handled"] is False


@pytest.mark.asyncio
async def test_list_contact_requests_admin_only(client):
    resp = await client.get("/api/cms/v1/contact-requests/")
    assert resp.status_code in (401, 403)

    resp = await client.get("/api/cms/v1/contact-requests/", headers=admin_headers())
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_filter_handled(client):
    # Create a handled and unhandled request
    await client.post(
        "/api/cms/v1/contact-requests/",
        json={"first_name": "A", "email": "a@test.com", "message": "Hi"},
    )

    resp = await client.get(
        "/api/cms/v1/contact-requests/?handled=false",
        headers=admin_headers(),
    )
    assert resp.status_code == 200
    for item in resp.json():
        assert item["handled"] is False


@pytest.mark.asyncio
async def test_update_contact_request(client):
    create_resp = await client.post(
        "/api/cms/v1/contact-requests/",
        json={"first_name": "B", "email": "b@test.com", "message": "Update me"},
    )
    cr_id = create_resp.json()["id"]

    resp = await client.patch(
        f"/api/cms/v1/contact-requests/{cr_id}",
        json={"handled": True},
        headers=admin_headers(),
    )
    assert resp.status_code == 200
    assert resp.json()["handled"] is True


@pytest.mark.asyncio
async def test_reply_contact_request(client):
    create_resp = await client.post(
        "/api/cms/v1/contact-requests/",
        json={"first_name": "C", "email": "c@test.com", "message": "Reply to me"},
    )
    cr_id = create_resp.json()["id"]

    resp = await client.post(
        f"/api/cms/v1/contact-requests/{cr_id}/reply",
        json={"reply_message": "Thank you for reaching out!"},
        headers=admin_headers(),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["handled"] is True
    assert data["reply_message"] == "Thank you for reaching out!"
    assert data["replied_at"] is not None


@pytest.mark.asyncio
async def test_stats(client):
    # Create unhandled request
    await client.post(
        "/api/cms/v1/contact-requests/",
        json={"first_name": "D", "email": "d@test.com", "message": "Stats test"},
    )

    resp = await client.get(
        "/api/cms/v1/contact-requests/stats",
        headers=admin_headers(),
    )
    assert resp.status_code == 200
    assert resp.json()["unhandled"] >= 1


@pytest.mark.asyncio
async def test_delete_contact_request(client):
    create_resp = await client.post(
        "/api/cms/v1/contact-requests/",
        json={"first_name": "E", "email": "e@test.com", "message": "Delete me"},
    )
    cr_id = create_resp.json()["id"]

    resp = await client.delete(
        f"/api/cms/v1/contact-requests/{cr_id}",
        headers=admin_headers(),
    )
    assert resp.status_code == 204
