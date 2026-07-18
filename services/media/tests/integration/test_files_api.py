"""Integration tests for File APIs."""

import io
import pytest
from tests.conftest import admin_headers, user_headers

@pytest.mark.asyncio
async def test_upload_file(client, override_storage_local):
    file_content = b"Hello, World!"
    files = {"file": ("test.txt", io.BytesIO(file_content), "text/plain")}
    
    resp = await client.post(
        "/api/media/v1/files/",
        files=files,
        headers=user_headers(),
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["original_filename"] == "test.txt"
    assert data["size"] == len(file_content)
    assert data["mime"] == "text/plain"
    assert data["is_public"] is False
    return data["id"]


@pytest.mark.asyncio
async def test_download_file(client, override_storage_local):
    # Upload first
    file_content = b"Hello, World!"
    files = {"file": ("test2.txt", io.BytesIO(file_content), "text/plain")}
    upload_resp = await client.post(
        "/api/media/v1/files/?is_public=true",
        files=files,
        headers=user_headers()
    )
    file_id = upload_resp.json()["id"]

    # Download public file without auth
    resp = await client.get(f"/api/media/v1/files/{file_id}")
    assert resp.status_code == 200
    assert resp.content == file_content
    assert resp.headers["Content-Length"] == str(len(file_content))


@pytest.mark.asyncio
async def test_download_private_file_forbidden(client, override_storage_local):
    # Upload private file
    file_content = b"Secret data"
    files = {"file": ("secret.txt", io.BytesIO(file_content), "text/plain")}
    upload_resp = await client.post(
        "/api/media/v1/files/",
        files=files,
        headers=user_headers()  # user_id 2
    )
    file_id = upload_resp.json()["id"]

    # Unauthenticated -> 401
    resp = await client.get(f"/api/media/v1/files/{file_id}")
    assert resp.status_code == 401

    # Different user (not admin) -> 403
    # Create another user token with id=3
    from tests.conftest import make_user_token
    other_user_headers = {"Authorization": f"Bearer {make_user_token(user_id=3)}"}
    resp = await client.get(f"/api/media/v1/files/{file_id}", headers=other_user_headers)
    assert resp.status_code == 403

    # Admin -> 200
    resp = await client.get(f"/api/media/v1/files/{file_id}", headers=admin_headers())
    assert resp.status_code == 200
    assert resp.content == file_content


@pytest.mark.asyncio
async def test_download_file_range(client, override_storage_local):
    # Upload first
    file_content = b"0123456789"
    files = {"file": ("range.txt", io.BytesIO(file_content), "text/plain")}
    upload_resp = await client.post(
        "/api/media/v1/files/?is_public=true",
        files=files,
        headers=user_headers()
    )
    file_id = upload_resp.json()["id"]

    # Range request
    resp = await client.get(
        f"/api/media/v1/files/{file_id}",
        headers={"Range": "bytes=2-5"}
    )
    assert resp.status_code == 206
    assert resp.content == b"2345"
    assert resp.headers["Content-Range"] == "bytes 2-5/10"


@pytest.mark.asyncio
async def test_delete_file(client, override_storage_local):
    # Upload first
    file_content = b"Delete me"
    files = {"file": ("del.txt", io.BytesIO(file_content), "text/plain")}
    upload_resp = await client.post(
        "/api/media/v1/files/",
        files=files,
        headers=user_headers() # user_id 2
    )
    file_id = upload_resp.json()["id"]

    # Delete as owner
    resp = await client.delete(
        f"/api/media/v1/files/{file_id}",
        headers=user_headers()
    )
    assert resp.status_code == 204

    # Ensure it's gone
    resp = await client.get(f"/api/media/v1/files/{file_id}", headers=admin_headers())
    assert resp.status_code == 404
