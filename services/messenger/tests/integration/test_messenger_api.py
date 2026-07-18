"""Integration tests for Messenger API."""

import json
from pathlib import Path

import pytest
import pytest_asyncio
from app.core.settings import settings
from tests.conftest import user_headers, admin_headers


@pytest_asyncio.fixture
async def seed_user2(client):
    """Ingest user_id=2 (default user_headers user) into chat_user_replicas."""
    await client.post(
        "/api/messenger/v1/users/ingest",
        json={"id": 2, "username": "user2", "first_name": "Test", "last_name": "User", "is_active": True, "avatar_url": None},
        headers=admin_headers(),
    )

@pytest.mark.asyncio
async def test_ingest_user_replica(client):
    resp = await client.post(
        "/api/messenger/v1/users/ingest",
        json={
            "id": 2,
            "username": "user2",
            "first_name": "Test",
            "last_name": "User",
            "is_active": True,
            "avatar_url": None
        },
        headers=admin_headers()
    )
    assert resp.status_code == 201


@pytest.mark.asyncio
async def test_create_and_list_room(client, seed_user2):
    # Ingest another user to participate
    await client.post(
        "/api/messenger/v1/users/ingest",
        json={"id": 3, "username": "user3", "first_name": "Test3", "last_name": "User3", "is_active": True, "avatar_url": None},
        headers=admin_headers()
    )

    resp = await client.post(
        "/api/messenger/v1/rooms/",
        json={"name": "Dev Chat", "room_type": "group", "participant_ids": [3]},
        headers=user_headers()  # user_id 2
    )
    assert resp.status_code == 201
    room_id = resp.json()["id"]

    # List rooms
    resp = await client.get("/api/messenger/v1/rooms/", headers=user_headers())
    assert resp.status_code == 200
    rooms = resp.json()
    assert len(rooms) >= 1
    
    return room_id


@pytest.mark.asyncio
async def test_send_and_list_messages(client, seed_user2):
    # Setup room
    await client.post(
        "/api/messenger/v1/users/ingest",
        json={"id": 3, "username": "user3", "first_name": "Test3", "last_name": "User3", "is_active": True, "avatar_url": None},
        headers=admin_headers(),
    )
    resp = await client.post(
        "/api/messenger/v1/rooms/",
        json={"name": "Dev Chat", "room_type": "group", "participant_ids": [3]},
        headers=user_headers(),
    )
    assert resp.status_code == 201
    room_id = resp.json()["id"]

    # Send message
    resp = await client.post(
        "/api/messenger/v1/messages/",
        json={"room_id": room_id, "content": "Hello World!"},
        headers=user_headers()
    )
    assert resp.status_code == 201

    # List messages
    resp = await client.get(f"/api/messenger/v1/messages/room/{room_id}", headers=user_headers())
    assert resp.status_code == 200
    msgs = resp.json()
    assert len(msgs) >= 1
    assert msgs[0]["content"] == "Hello World!"


@pytest.mark.asyncio
async def test_upload_attachment_is_stored_by_room_and_linked_to_message(client, seed_user2, tmp_path):
    original_attachment_dir = settings.attachment_dir
    settings.attachment_dir = str(tmp_path)
    try:
        await client.post(
            "/api/messenger/v1/users/ingest",
            json={"id": 3, "username": "user3", "first_name": "Test3", "last_name": "User3", "is_active": True, "avatar_url": None},
            headers=admin_headers(),
        )
        resp = await client.post(
            "/api/messenger/v1/rooms/",
            json={"name": "Files", "room_type": "group", "participant_ids": [3]},
            headers=user_headers(),
        )
        assert resp.status_code == 201
        room = resp.json()
        room_id = room["id"]
        storage_key = room["storage_key"]

        upload_resp = await client.post(
            "/api/messenger/v1/attachments/upload/",
            data={"room_id": str(room_id)},
            files={"file": ("note.txt", b"hello", "text/plain")},
            headers=user_headers(),
        )
        assert upload_resp.status_code == 201
        attachment = upload_resp.json()
        assert attachment["room_id"] == room_id
        assert attachment["data_type"] == "documents"
        assert f"/chats/{storage_key}/documents/" in attachment["url"]

        relative_url = attachment["url"].split("/api/messenger/v1/attachments/files/", 1)[1]
        stored_file = tmp_path / Path(*relative_url.split("/"))
        assert stored_file.read_bytes() == b"hello"

        send_resp = await client.post(
            "/api/messenger/v1/messages/",
            json={
                "room_id": room_id,
                "content": json.dumps({"text": "attached"}),
                "attachment_ids": [attachment["id"]],
            },
            headers=user_headers(),
        )
        assert send_resp.status_code == 201
        message = send_resp.json()
        assert message["attachments"][0]["id"] == attachment["id"]
        assert message["attachments"][0]["url"] == attachment["url"]

        list_resp = await client.get(
            f"/api/messenger/v1/messages/room/{room_id}",
            headers=user_headers(),
        )
        assert list_resp.status_code == 200
        assert list_resp.json()[0]["attachments"][0]["id"] == attachment["id"]

        metadata_path = tmp_path / "chats" / storage_key / "metadata" / f"{attachment['id']}.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        assert metadata["message_id"] == message["id"]
    finally:
        settings.attachment_dir = original_attachment_dir


@pytest.mark.asyncio
async def test_e2ee_keys(client, seed_user2):
    resp = await client.post(
        "/api/messenger/v1/keys/",
        json={
            "device_id": "device_1",
            "public_identity_key": "id_key",
            "signed_pre_key": "pre_key",
            "signature": "sig"
        },
        headers=user_headers()
    )
    assert resp.status_code == 201

    resp = await client.get("/api/messenger/v1/keys/2", headers=user_headers())
    assert resp.status_code == 200
    assert len(resp.json()) == 1
    assert resp.json()[0]["device_id"] == "device_1"
