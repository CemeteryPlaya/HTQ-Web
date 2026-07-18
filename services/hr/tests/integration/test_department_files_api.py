"""Department file API tests."""

import pytest

from app.models.department import Department
from tests.conftest import admin_headers


@pytest.mark.asyncio
async def test_admin_can_manage_department_files(client, session, monkeypatch):
    department = Department(name="Engineering", path="engineering", description="", is_active=True)
    session.add(department)
    await session.commit()
    await session.refresh(department)

    async def fake_upload_to_media(*, request, file):
        return {
            "id": "media-123",
            "original_filename": file.filename,
            "url": "/api/media/v1/files/media-123/download/",
            "size": 3,
            "mime": file.content_type,
        }

    monkeypatch.setattr("app.api.v1.department_files._upload_to_media", fake_upload_to_media)

    headers = admin_headers()
    folders_resp = await client.get("/api/hr/v1/department-folders/", headers=headers)
    assert folders_resp.status_code == 200
    assert folders_resp.json() == [
        {
            "id": department.id,
            "department": department.id,
            "department_name": "Engineering",
            "files_count": 0,
            "created_at": folders_resp.json()[0]["created_at"],
        }
    ]

    file_folders_resp = await client.get(
        f"/api/hr/v1/department-file-folders/?department={department.id}",
        headers=headers,
    )
    assert file_folders_resp.status_code == 200
    assert file_folders_resp.json() == []

    create_folder_resp = await client.post(
        "/api/hr/v1/department-file-folders/",
        headers=headers,
        json={"department": department.id, "name": "Policies"},
    )
    assert create_folder_resp.status_code == 201
    created_folder = create_folder_resp.json()
    assert created_folder["department"] == department.id
    assert created_folder["name"] == "Policies"
    assert created_folder["files_count"] == 0

    duplicate_folder_resp = await client.post(
        "/api/hr/v1/department-file-folders/",
        headers=headers,
        json={"department": department.id, "name": "policies"},
    )
    assert duplicate_folder_resp.status_code == 409

    upload_resp = await client.post(
        "/api/hr/v1/department-files/",
        headers=headers,
        data={"folder": str(department.id), "description": "Team policy"},
        files={"file": ("policy.txt", b"abc", "text/plain")},
    )
    assert upload_resp.status_code == 201
    created = upload_resp.json()
    assert created["folder"] == department.id
    assert created["file_folder"] is None
    assert created["name"] == "policy.txt"
    assert created["file_url"] == "/api/media/v1/files/media-123/download/"
    assert created["description"] == "Team policy"

    folder_upload_resp = await client.post(
        "/api/hr/v1/department-files/",
        headers=headers,
        data={
            "folder": str(department.id),
            "file_folder": str(created_folder["id"]),
            "description": "Folder copy",
        },
        files={"file": ("policy-folder.txt", b"abc", "text/plain")},
    )
    assert folder_upload_resp.status_code == 201
    folder_file = folder_upload_resp.json()
    assert folder_file["file_folder"] == created_folder["id"]

    files_resp = await client.get(
        f"/api/hr/v1/department-files/?folder={department.id}",
        headers=headers,
    )
    assert files_resp.status_code == 200
    assert {row["id"] for row in files_resp.json()} == {created["id"], folder_file["id"]}

    root_files_resp = await client.get(
        f"/api/hr/v1/department-files/?folder={department.id}&root_only=true",
        headers=headers,
    )
    assert root_files_resp.status_code == 200
    assert [row["id"] for row in root_files_resp.json()] == [created["id"]]

    folder_files_resp = await client.get(
        f"/api/hr/v1/department-files/?folder={department.id}&file_folder={created_folder['id']}",
        headers=headers,
    )
    assert folder_files_resp.status_code == 200
    assert [row["id"] for row in folder_files_resp.json()] == [folder_file["id"]]

    file_folders_resp = await client.get(
        f"/api/hr/v1/department-file-folders/?department={department.id}",
        headers=headers,
    )
    assert file_folders_resp.status_code == 200
    assert file_folders_resp.json()[0]["files_count"] == 1

    folders_resp = await client.get("/api/hr/v1/department-folders/", headers=headers)
    assert folders_resp.status_code == 200
    assert folders_resp.json()[0]["files_count"] == 2

    delete_resp = await client.delete(f"/api/hr/v1/department-files/{created['id']}/", headers=headers)
    assert delete_resp.status_code == 204

    delete_folder_file_resp = await client.delete(
        f"/api/hr/v1/department-files/{folder_file['id']}/",
        headers=headers,
    )
    assert delete_folder_file_resp.status_code == 204

    files_resp = await client.get(
        f"/api/hr/v1/department-files/?folder={department.id}",
        headers=headers,
    )
    assert files_resp.status_code == 200
    assert files_resp.json() == []
