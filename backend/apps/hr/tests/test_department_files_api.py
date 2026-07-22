"""Контракт /api/hr/v1/department-{folders,file-folders,files}/* — паритет с
services/hr/app/api/v1/department_files.py.

Провенанс форм ответов: schemas/department_file.py (DepartmentFolderOut,
DepartmentFileFolderOut, DepartmentFileOut).

Зафиксированные ловушки паритета (проверяются тестами ниже):
  * не-админ видит только СВОЙ отдел (по Employee.department_id); админ — все;
  * загрузка файла — реальный apps.media_files.interface.store_file(scope=
    "hr_department", internal_authorized=True) — hr_department RESTRICTED,
    "internal_authorized" здесь ЗАМЕНЯЕТ HTTP-проксирование исходника
    (department-уровневый access-check УЖЕ прошёл на этом этапе);
  * create-folder: 409 при коллизии имени (регистронезависимо) в том же
    отделе; 400 при пустом/whitespace-only имени;
  * search — регистронезависимо по name/description, только в доступных
    отделах для не-админа;
  * DELETE файла — 204, проверка department-доступа по СУЩЕСТВУЮЩЕЙ строке.

Странности источника, сознательно НЕ портируемые (см. отчёт):
  * httpx-проксирование к media-service заменено прямым in-process вызовом
    apps.media_files.interface — сетевых 502 "media-service unavailable"
    здесь в принципе быть не может;
  * Redis pub/sub-уведомление messenger-бота "Файлы" о новом файле отдела
    (notify.file_access_request) — тот же класс решений, что дропнутый
    dramatiq (Р2): подписчика этого канала в Django-монолите ещё нет.

План: docs/plans/2026-07-20-hr-domain.md
"""
from __future__ import annotations

import datetime

import pytest
from django.db import connection
from django.test import Client
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.hr.models import Department, DepartmentFile, DepartmentFileFolder, Employee, Position
from apps.users.models import User, UserStatus
from htqweb.authn.jwt import issue_token_pair

BASE = "/api/hr/v1"


class _FakeStorage:
    """In-memory htqweb.storage.Storage double — same pattern as
    apps/users/tests/test_avatar_e2e.py's ``shared_storage``. Real network
    S3/MinIO is not available in this test run (STORAGE_BACKEND defaults to
    "s3" and is not overridden by settings/test.py)."""

    def __init__(self):
        self.objects: dict[str, bytes] = {}

    def save(self, path, data, content_type=None):
        self.objects[path] = data

    def open(self, path, byte_range=None):
        data = self.objects[path]
        if byte_range is not None:
            start, end = byte_range
            return data[start : end + 1]
        return data

    def delete(self, path):
        self.objects.pop(path, None)

    def exists(self, path):
        return path in self.objects

    def size(self, path):
        return len(self.objects[path])


@pytest.fixture(autouse=True)
def fake_media_storage(monkeypatch):
    from apps.media_files.services import upload_service as media_upload_service

    storage = _FakeStorage()
    monkeypatch.setattr(media_upload_service, "get_storage", lambda bucket=None: storage)
    return storage


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


def _emp(dep, pos, email, user_id, **kw):
    return Employee.objects.create(
        first_name="И", last_name="И", email=email, department=dep, position=pos,
        hire_date=datetime.date(2024, 1, 9), user_id=user_id, **kw,
    )


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


@pytest.fixture
def admin_auth(db):
    _user, headers = _user_auth("hradmin", is_staff=True)
    return headers


@pytest.fixture
def dep(db):
    return _dep("ИТ", "it")


@pytest.fixture
def other_dep(db):
    return _dep("Финансы", "fin")


@pytest.fixture
def dep_employee_auth(db, dep):
    """Non-admin JWT belonging to an Employee row in ``dep``."""
    user, headers = _user_auth("deptmember")
    pos = _pos("Инженер", dep, weight=50)
    _emp(dep, pos, "deptmember@htq.test", user.id)
    return headers


@pytest.fixture
def outsider_auth(db, other_dep):
    """Non-admin JWT belonging to an Employee row in a DIFFERENT department."""
    user, headers = _user_auth("outsider")
    pos = _pos("Финансист", other_dep, weight=60)
    _emp(other_dep, pos, "outsider@htq.test", user.id)
    return headers


# ── schema паритет ───────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_department_file_folder_columns_and_indexes():
    cols = _cols("hr_departmentfilefolder")
    assert not cols["name"]["nullable"]
    assert cols["created_by_user_id"]["nullable"]
    assert "created_at" in cols and "updated_at" in cols
    assert {"department_id", "created_by_user_id"} <= _indexed_columns("hr_departmentfilefolder")


@pytest.mark.django_db
def test_department_file_columns_and_indexes():
    cols = _cols("hr_departmentfile")
    assert not cols["name"]["nullable"]
    assert not cols["media_file_id"]["nullable"]
    assert cols["file_folder_id"]["nullable"]
    assert cols["file_size"]["default"] is not None
    assert cols["mime_type"]["default"] is not None
    assert {"department_id", "file_folder_id", "media_file_id", "uploaded_by_user_id"} <= _indexed_columns(
        "hr_departmentfile"
    )


@pytest.mark.django_db
def test_folder_name_unique_per_department_constraint():
    dep = _dep("ИТ", "it")
    DepartmentFileFolder.objects.create(department=dep, name="Приказы")
    from django.db.utils import IntegrityError

    with pytest.raises(IntegrityError):
        DepartmentFileFolder.objects.create(department=dep, name="Приказы")


# ── auth ────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_requires_jwt():
    assert Client().get(f"{BASE}/department-folders/").status_code == 401


# ── GET /department-folders/ ─────────────────────────────────────────────────

@pytest.mark.django_db
def test_department_folders_admin_sees_all(admin_auth, dep, other_dep):
    body = Client().get(f"{BASE}/department-folders/", **admin_auth).json()
    assert {d["department"] for d in body} == {dep.id, other_dep.id}


@pytest.mark.django_db
def test_department_folders_employee_sees_only_own(dep_employee_auth, dep, other_dep):
    body = Client().get(f"{BASE}/department-folders/", **dep_employee_auth).json()
    assert [d["department"] for d in body] == [dep.id]


# ── department-file-folders ──────────────────────────────────────────────────

@pytest.mark.django_db
def test_create_and_list_file_folder(dep_employee_auth, dep):
    resp = Client().post(
        f"{BASE}/department-file-folders/",
        data={"department": dep.id, "name": "Приказы"},
        content_type="application/json", **dep_employee_auth,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "Приказы"
    assert body["files_count"] == 0
    assert body["created_by_name"]

    listed = Client().get(
        f"{BASE}/department-file-folders/?department={dep.id}", **dep_employee_auth,
    ).json()
    assert [f["name"] for f in listed] == ["Приказы"]


@pytest.mark.django_db
def test_create_file_folder_duplicate_name_409(dep_employee_auth, dep):
    Client().post(
        f"{BASE}/department-file-folders/",
        data={"department": dep.id, "name": "Приказы"},
        content_type="application/json", **dep_employee_auth,
    )
    resp = Client().post(
        f"{BASE}/department-file-folders/",
        data={"department": dep.id, "name": "приказы"},  # case-insensitive collision
        content_type="application/json", **dep_employee_auth,
    )
    assert resp.status_code == 409


@pytest.mark.django_db
def test_create_file_folder_blank_name_400(dep_employee_auth, dep):
    resp = Client().post(
        f"{BASE}/department-file-folders/",
        data={"department": dep.id, "name": "   "},
        content_type="application/json", **dep_employee_auth,
    )
    assert resp.status_code == 400


@pytest.mark.django_db
def test_outsider_denied_department_access(outsider_auth, dep):
    resp = Client().get(f"{BASE}/department-file-folders/?department={dep.id}", **outsider_auth)
    assert resp.status_code == 403


@pytest.mark.django_db
def test_unknown_department_404(dep_employee_auth):
    resp = Client().get(f"{BASE}/department-file-folders/?department=999999", **dep_employee_auth)
    assert resp.status_code == 404


# ── department-files: upload/list/delete ─────────────────────────────────────

@pytest.mark.django_db
def test_upload_list_delete_department_file(dep_employee_auth, dep):
    upload = SimpleUploadedFile("report.txt", b"hello department", content_type="text/plain")
    resp = Client().post(
        f"{BASE}/department-files/",
        data={"folder": str(dep.id), "file": upload, "description": "Q1"},
        **dep_employee_auth,
    )
    assert resp.status_code == 201
    created = resp.json()
    assert created["name"] == "report.txt"
    assert created["description"] == "Q1"
    assert created["file_size"] == len(b"hello department")
    assert created["file_url"]

    row = DepartmentFile.objects.get(id=created["id"])
    assert row.department_id == dep.id
    assert row.media_file_id

    listed = Client().get(
        f"{BASE}/department-files/?folder={dep.id}", **dep_employee_auth,
    ).json()
    assert [f["id"] for f in listed] == [created["id"]]

    del_resp = Client().delete(f"{BASE}/department-files/{created['id']}/", **dep_employee_auth)
    assert del_resp.status_code == 204
    assert not DepartmentFile.objects.filter(id=created["id"]).exists()


@pytest.mark.django_db
def test_upload_into_file_folder_and_root_only_filter(dep_employee_auth, dep):
    folder = DepartmentFileFolder.objects.create(department=dep, name="Приказы")

    upload1 = SimpleUploadedFile("in_folder.txt", b"a", content_type="text/plain")
    r1 = Client().post(
        f"{BASE}/department-files/",
        data={"folder": str(dep.id), "file_folder": str(folder.id), "file": upload1},
        **dep_employee_auth,
    )
    assert r1.status_code == 201

    upload2 = SimpleUploadedFile("root.txt", b"b", content_type="text/plain")
    r2 = Client().post(
        f"{BASE}/department-files/", data={"folder": str(dep.id), "file": upload2}, **dep_employee_auth,
    )
    assert r2.status_code == 201

    root_only = Client().get(
        f"{BASE}/department-files/?folder={dep.id}&root_only=true", **dep_employee_auth,
    ).json()
    assert [f["name"] for f in root_only] == ["root.txt"]

    in_folder = Client().get(
        f"{BASE}/department-files/?folder={dep.id}&file_folder={folder.id}", **dep_employee_auth,
    ).json()
    assert [f["name"] for f in in_folder] == ["in_folder.txt"]


@pytest.mark.django_db
def test_delete_outsider_denied(dep_employee_auth, outsider_auth, dep):
    upload = SimpleUploadedFile("secret.txt", b"x", content_type="text/plain")
    created = Client().post(
        f"{BASE}/department-files/", data={"folder": str(dep.id), "file": upload}, **dep_employee_auth,
    ).json()

    resp = Client().delete(f"{BASE}/department-files/{created['id']}/", **outsider_auth)
    assert resp.status_code == 403
    assert DepartmentFile.objects.filter(id=created["id"]).exists()


@pytest.mark.django_db
def test_delete_missing_file_404(dep_employee_auth):
    resp = Client().delete(f"{BASE}/department-files/999999/", **dep_employee_auth)
    assert resp.status_code == 404


# ── search ────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_search_matches_name_or_description_case_insensitive(dep_employee_auth, dep):
    DepartmentFile.objects.create(
        department=dep, media_file_id="m1", name="Годовой отчёт.pdf",
        file_url="/x", description="",
    )
    DepartmentFile.objects.create(
        department=dep, media_file_id="m2", name="other.pdf",
        file_url="/y", description="содержит ГОДОВОЙ план",
    )
    DepartmentFile.objects.create(
        department=dep, media_file_id="m3", name="unrelated.pdf", file_url="/z",
    )

    body = Client().get(f"{BASE}/department-files/search/?q=годовой", **dep_employee_auth).json()
    assert {f["name"] for f in body} == {"Годовой отчёт.pdf", "other.pdf"}


@pytest.mark.django_db
def test_search_scoped_to_accessible_departments_for_non_admin(dep_employee_auth, dep, other_dep):
    DepartmentFile.objects.create(department=dep, media_file_id="m1", name="mine.pdf", file_url="/x")
    DepartmentFile.objects.create(department=other_dep, media_file_id="m2", name="mine-too.pdf", file_url="/y")

    body = Client().get(f"{BASE}/department-files/search/?q=mine", **dep_employee_auth).json()
    assert {f["name"] for f in body} == {"mine.pdf"}


@pytest.mark.django_db
def test_search_requires_nonempty_q(dep_employee_auth):
    resp = Client().get(f"{BASE}/department-files/search/?q=", **dep_employee_auth)
    assert resp.status_code == 422
