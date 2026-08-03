"""Контракт /api/hr/v1/{documents,mongo-documents}/* + GET
/employees/{id}/documents — паритет с services/hr/app/api/v1/{documents,
mongo_documents,employees}.py.

Провенанс формы ответов: app/schemas/document.py (DocumentOut), app/schemas/
mongo_document.py (HRDocumentOut), поведение — apps/hr/services/document_service.py.

Авторизация (docs/plans/2026-07-20-hr-domain.md, под-модуль hr-docs):
  * /documents/* — БУКВАЛЬНО ``get_current_user`` исходника на ВСЕХ 4
    эндпойнтах, включая POST/DELETE (исходник НЕ зовёт require_hr_write в
    documents.py — странность, не баг порта, как у recruiting/time-core);
  * /mongo-documents/* — reads (list/get) = ``get_current_user`` -> auth="jwt";
    writes (create/update/delete) = ``require_hr_write`` -> admin=True;
  * /employees/{id}/documents — require_hr_access + _require_visible_employee
    (та же пара, что history), НЕ admin=True.

Зафиксированные ловушки паритета (проверяются тестами ниже):
  * /documents/ список — конверт PaginatedResponse {items,total,page,pages,limit};
  * /mongo-documents/ список — ГОЛЫЙ список (НЕ PaginatedResponse-конверт);
  * DocumentCreate.metadata_ (alias "metadata") — wire-ключ "metadata" и на
    входе, и на выходе (DocumentOut);
  * mongo-documents doc_id — теперь integer PK (не ObjectId); не-числовой
    doc_id -> 400 "Invalid document ID format" (тот же смысл, что InvalidId
    исходника), отсутствующий id -> 404;
  * PATCH /mongo-documents/{doc_id} — частичное обновление (exclude_unset),
    непереданные поля не затираются;
  * employees/{id}/documents — Document по employee_id, order_by created_at
    desc, форма как DocumentOut; скрытый отдел -> 404 "Employee not found".

План: docs/plans/2026-07-20-hr-domain.md
"""
from __future__ import annotations

import datetime

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

from apps.hr.models import Department, Document, Employee, EmployeeDocumentBlob, Position
from apps.users.models import User, UserStatus
from htqweb.authn.jwt import issue_token_pair

BASE = "/api/hr/v1/documents"
MBASE = "/api/hr/v1/mongo-documents"
EBASE = "/api/hr/v1/employees"


@pytest.fixture
def dep(db):
    return Department.objects.create(name="ИТ", path="it")


@pytest.fixture
def pos(db, dep):
    return Position.objects.create(title="Инженер", department=dep, weight=100)


@pytest.fixture
def emp(db, dep, pos):
    return Employee.objects.create(
        first_name="И", last_name="И", email="emp-docs@htq.test", department=dep, position=pos,
        hire_date=datetime.date(2024, 1, 9),
    )


@pytest.fixture
def auth(db):
    """Обычный вошедший пользователь — годится для ЛЮБОГО /documents/*
    эндпойнта (исходник нигде не зовёт require_hr_write в documents.py) и
    для reads /mongo-documents/*."""
    user = User.objects.create(
        username="doc-user", email="doc-user@htq.test", password="x", status=UserStatus.ACTIVE,
    )
    user.set_password("S3cret!Pass1")
    user.save()
    return {"HTTP_AUTHORIZATION": f"Bearer {issue_token_pair(user)['access']}"}


@pytest.fixture
def admin_auth(db):
    """is_staff=True — elevated, требуется для /mongo-documents/* writes
    (require_hr_write) и для /employees/{id}/documents (require_hr_access)."""
    user = User.objects.create(
        username="doc-admin", email="doc-admin@htq.test", password="x", status=UserStatus.ACTIVE,
        is_staff=True,
    )
    user.set_password("Adm1n!Pass")
    user.save()
    return {"HTTP_AUTHORIZATION": f"Bearer {issue_token_pair(user)['access']}"}


def _doc(emp, **kw):
    defaults = {
        "title": "Трудовой договор", "doc_type": "contract",
        "file_path": "/files/a.pdf", "file_size": 100,
    }
    defaults.update(kw)
    return Document.objects.create(employee=emp, uploaded_by=emp, **defaults)


def _create_payload(emp, **kw):
    payload = {
        "employee_id": emp.id, "title": "Приказ", "doc_type": "order",
        "file_path": "/files/order.pdf", "file_size": 200, "uploaded_by": emp.id,
    }
    payload.update(kw)
    return payload


# ═══════════════════════════════════════════════════════════════════════════
#  /documents/*
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_documents_list_requires_jwt():
    assert Client().get(f"{BASE}/").status_code == 401


@pytest.mark.django_db
def test_documents_list_paginated_envelope(auth, emp):
    _doc(emp, title="Первый")
    _doc(emp, title="Второй")

    resp = Client().get(f"{BASE}/", **auth)
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"items", "total", "page", "pages", "limit"}
    assert body["total"] == 2
    assert body["page"] == 1
    assert body["limit"] == 20
    # order_by created_at desc — последний созданный первый
    assert body["items"][0]["title"] == "Второй"


@pytest.mark.django_db
def test_upload_document_plain_jwt_user_can_write(auth, emp):
    """Странность исходника: обычный jwt-пользователь БЕЗ HR-роли может
    создавать документы — documents.py нигде не зовёт require_hr_write."""
    resp = Client().post(
        f"{BASE}/", data=_create_payload(emp, metadata={"k": "v"}),
        content_type="application/json", **auth,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["title"] == "Приказ"
    assert body["employee_id"] == emp.id
    assert body["uploaded_by"] == emp.id
    assert body["metadata"] == {"k": "v"}
    assert body["mime_type"] == "application/octet-stream"
    assert set(body) == {
        "id", "employee_id", "title", "doc_type", "file_path", "file_size",
        "mime_type", "metadata", "uploaded_by", "created_at", "updated_at",
    }


@pytest.mark.django_db
def test_upload_document_requires_jwt_at_all(emp):
    resp = Client().post(
        f"{BASE}/", data=_create_payload(emp), content_type="application/json",
    )
    assert resp.status_code == 401


@pytest.mark.django_db
def test_upload_document_metadata_alias_accepts_wire_key(auth, emp):
    """DocumentCreate.metadata_ — alias "metadata" (populate_by_name) —
    буквальный порт: клиент шлёт JSON-ключ "metadata", не "metadata_"."""
    resp = Client().post(
        f"{BASE}/", data=_create_payload(emp, metadata={"issued_by": "HR"}),
        content_type="application/json", **auth,
    )
    assert resp.status_code == 201
    assert resp.json()["metadata"] == {"issued_by": "HR"}


@pytest.mark.django_db
def test_get_document_not_found(auth):
    assert Client().get(f"{BASE}/999999/", **auth).status_code == 404


@pytest.mark.django_db
def test_get_document_returns_full_shape(auth, emp):
    doc = _doc(emp)
    resp = Client().get(f"{BASE}/{doc.id}/", **auth)
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == doc.id
    assert body["doc_type"] == "contract"


@pytest.mark.django_db
def test_delete_document_plain_jwt_user_can_delete(auth, emp):
    doc = _doc(emp)
    resp = Client().delete(f"{BASE}/{doc.id}/", **auth)
    assert resp.status_code == 204
    assert Client().get(f"{BASE}/{doc.id}/", **auth).status_code == 404


@pytest.mark.django_db
def test_delete_document_not_found(auth):
    assert Client().delete(f"{BASE}/999999/", **auth).status_code == 404


@pytest.mark.django_db(transaction=True)
def test_upload_document_invalid_employee_id_500(auth, emp):
    """Контракт, не баг: ни documents.py, ни BaseRepository.create исходника
    не проверяют существование employee_id/uploaded_by заранее — невалидный
    FK падает в IntegrityError необработанным -> api_view отдаёт 500.

    ⚠️ transaction=True обязателен: Django создаёт FK-констрейнты как
    DEFERRABLE INITIALLY DEFERRED (проверка на COMMIT, не на INSERT). В обычном
    @django_db тесте всё завёрнуто в откатываемую транзакцию, которая никогда
    не коммитится, поэтому отложенный FK НЕ срабатывает и вставка выглядит
    успешной (201) — это артефакт теста, а не прод-поведение. С transaction=True
    вьюха работает в autocommit, INSERT коммитится, отложенный FK срабатывает
    сразу -> IntegrityError -> 500, ровно как в проде и в исходнике (там FK
    немедленный). UNIQUE-констрейнты, в отличие от FK, немедленные — поэтому
    test_create_duplicate_entry_500 (time) ловит 500 и без transaction=True."""
    resp = Client().post(
        f"{BASE}/", data=_create_payload(emp, employee_id=999999),
        content_type="application/json", **auth,
    )
    assert resp.status_code == 500


# ═══════════════════════════════════════════════════════════════════════════
#  POST /documents/ — multipart-ветка (сверх портированного контракта)
# ═══════════════════════════════════════════════════════════════════════════
#
# JSON-контракт исходника ждёт уже загруженный куда-то файл (file_path/
# file_size/mime_type/uploaded_by от клиента). Фронт HR-«Документов» шлёт
# обычную форму с файлом — она разбивалась о JSON-парсер (422 "Invalid
# JSON"). Ветка добавлена по образцу /department-files/: байты уезжают в
# apps.media_files через его interface, сюда пишется ссылка.
#
# Хранилище подменяем тем же способом, что test_department_files_api.py:
# настоящего S3/MinIO в тестовом прогоне нет.


# Скоуп hr_doc в media — PDF-only с проверкой сигнатуры (scope_policy.py),
# поэтому в тестах нужен файл, который реально начинается с %PDF.
_PDF_BYTES = (
    b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n"
)


def _pdf(name: str = "doc.pdf") -> SimpleUploadedFile:
    return SimpleUploadedFile(name, _PDF_BYTES, content_type="application/pdf")


class _FakeStorage:
    def __init__(self):
        self.objects: dict[str, bytes] = {}

    def save(self, path, data, content_type=None):
        self.objects[path] = data

    def open(self, path, byte_range=None):
        return self.objects[path]

    def delete(self, path):
        self.objects.pop(path, None)

    def exists(self, path):
        return path in self.objects

    def size(self, path):
        return len(self.objects[path])


@pytest.fixture
def fake_media_storage(monkeypatch):
    from apps.media_files.services import upload_service as media_upload_service

    storage = _FakeStorage()
    monkeypatch.setattr(media_upload_service, "get_storage", lambda bucket=None: storage)
    return storage


@pytest.fixture
def hr_uploader_auth(db, dep, pos):
    """HR-сотрудник с правом записи (is_staff) И карточкой Employee.

    Оба условия обязательны: скоуп ``hr_doc`` в media — restricted, поэтому
    вьюха сначала проверяет HR-доступ, а ``Document.uploaded_by`` — NOT NULL
    FK на Employee, поэтому загрузить документ от лица пользователя без
    карточки некуда.
    """
    user = User.objects.create(
        username="doc-uploader", email="doc-uploader@htq.test", password="x",
        status=UserStatus.ACTIVE, is_staff=True,
    )
    user.set_password("Adm1n!Pass")
    user.save()
    Employee.objects.create(
        first_name="Загрузчик", last_name="Кадровик", email="doc-uploader@htq.test",
        department=dep, position=pos, hire_date=datetime.date(2024, 1, 9), user_id=user.id,
    )
    return {"HTTP_AUTHORIZATION": f"Bearer {issue_token_pair(user)['access']}"}


@pytest.mark.django_db
def test_multipart_upload_creates_document(hr_uploader_auth, emp, fake_media_storage):
    upload = _pdf("contract.pdf")
    resp = Client().post(
        f"{BASE}/",
        data={
            "employee": str(emp.id), "title": "Трудовой договор",
            "doc_type": "contract", "description": "скан", "file": upload,
        },
        **hr_uploader_auth,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["employee_id"] == emp.id
    assert body["title"] == "Трудовой договор"
    assert body["file_size"] == len(_PDF_BYTES)
    # Ссылка на media + description, которому в модели колонки нет, — в metadata.
    assert body["metadata"]["media_file_id"]
    assert body["metadata"]["description"] == "скан"
    assert body["file_path"].startswith("/api/media/v1/files/")
    assert fake_media_storage.objects, "файл должен уехать в хранилище"


@pytest.mark.django_db
def test_multipart_upload_appears_in_list(hr_uploader_auth, emp, fake_media_storage):
    Client().post(
        f"{BASE}/",
        data={
            "employee": str(emp.id), "title": "Приказ", "doc_type": "order",
            "file": _pdf("order.pdf"),
        },
        **hr_uploader_auth,
    )
    resp = Client().get(f"{BASE}/", **hr_uploader_auth)
    assert resp.status_code == 200
    assert [d["title"] for d in resp.json()["items"]] == ["Приказ"]


@pytest.mark.django_db
def test_multipart_upload_without_file_422(hr_uploader_auth, emp, fake_media_storage):
    resp = Client().post(
        f"{BASE}/", data={"employee": str(emp.id), "title": "Без файла"}, **hr_uploader_auth,
    )
    assert resp.status_code == 422


@pytest.mark.django_db
def test_multipart_upload_unknown_employee_404(hr_uploader_auth, fake_media_storage):
    resp = Client().post(
        f"{BASE}/",
        data={
            "employee": "999999", "title": "Ничей документ",
            "file": _pdf(),
        },
        **hr_uploader_auth,
    )
    assert resp.status_code == 404


@pytest.mark.django_db
def test_multipart_upload_without_employee_card_succeeds(admin_auth, emp, fake_media_storage):
    """admin_auth — is_staff без карточки Employee.

    Документы грузят и платформенные учётки, поэтому ``uploaded_by``
    сделан nullable (миграция 0015). Авторство при этом не теряется —
    id пользователя уезжает в metadata.
    """
    resp = Client().post(
        f"{BASE}/",
        data={
            "employee": str(emp.id), "title": "Договор",
            "file": _pdf(),
        },
        **admin_auth,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["uploaded_by"] is None
    assert body["metadata"]["uploaded_by_user_id"] == User.objects.get(username="doc-admin").id


@pytest.mark.django_db
def test_multipart_upload_denied_without_hr_write(auth, emp, fake_media_storage):
    """Обычный пользователь: JSON-ветка ему открыта (странность исходника),
    но за запись в restricted-скоуп media вьюха ручается только при HR-праве."""
    resp = Client().post(
        f"{BASE}/",
        data={
            "employee": str(emp.id), "title": "Договор",
            "file": _pdf(),
        },
        **auth,
    )
    assert resp.status_code == 403


@pytest.mark.django_db
def test_json_contract_still_works_alongside_multipart(auth, emp):
    """Ветка выбирается по Content-Type — портированный JSON-путь не задет."""
    resp = Client().post(
        f"{BASE}/", data=_create_payload(emp), content_type="application/json", **auth,
    )
    assert resp.status_code == 201
    assert resp.json()["file_path"] == "/files/order.pdf"


# ═══════════════════════════════════════════════════════════════════════════
#  /mongo-documents/*  (ex-Mongo -> EmployeeDocumentBlob JSONB, решение D6)
# ═══════════════════════════════════════════════════════════════════════════

def _mongo_payload(emp, **kw):
    payload = {
        "sql_employee_id": emp.id, "title": "Полис ДМС", "doc_type": "policy",
        "content": "текст", "tags": ["dms"], "metadata": {"year": 2026},
    }
    payload.update(kw)
    return payload


@pytest.mark.django_db
def test_mongo_documents_list_requires_jwt():
    assert Client().get(f"{MBASE}/").status_code == 401


@pytest.mark.django_db
def test_mongo_documents_list_is_bare_list_not_paginated_envelope(auth, emp, admin_auth):
    Client().post(
        f"{MBASE}/", data=_mongo_payload(emp), content_type="application/json", **admin_auth,
    )
    resp = Client().get(f"{MBASE}/", **auth)
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert len(body) == 1
    assert set(body[0]) == {
        "id", "sql_employee_id", "title", "doc_type", "content", "file_url",
        "file_size_bytes", "mime_type", "tags", "metadata", "created_at",
        "updated_at", "created_by_user_id",
    }


@pytest.mark.django_db
def test_mongo_documents_list_filters_by_employee_and_doc_type(auth, emp, admin_auth):
    other = Employee.objects.create(
        first_name="Д", last_name="Д", email="other-docs@htq.test",
        department=emp.department, position=emp.position, hire_date=datetime.date(2024, 1, 9),
    )
    Client().post(
        f"{MBASE}/", data=_mongo_payload(emp, doc_type="policy"),
        content_type="application/json", **admin_auth,
    )
    Client().post(
        f"{MBASE}/", data=_mongo_payload(other, doc_type="memo", title="Служебка"),
        content_type="application/json", **admin_auth,
    )

    resp = Client().get(f"{MBASE}/?employee_id={emp.id}", **auth)
    body = resp.json()
    assert len(body) == 1
    assert body[0]["sql_employee_id"] == emp.id

    resp = Client().get(f"{MBASE}/?doc_type=memo", **auth)
    body = resp.json()
    assert len(body) == 1
    assert body[0]["doc_type"] == "memo"


@pytest.mark.django_db
def test_create_mongo_document_requires_admin(auth, emp):
    resp = Client().post(
        f"{MBASE}/", data=_mongo_payload(emp), content_type="application/json", **auth,
    )
    assert resp.status_code == 403


@pytest.mark.django_db
def test_create_mongo_document_requires_jwt_at_all(emp):
    resp = Client().post(
        f"{MBASE}/", data=_mongo_payload(emp), content_type="application/json",
    )
    assert resp.status_code == 401


@pytest.mark.django_db
def test_create_mongo_document_success(admin_auth, emp):
    resp = Client().post(
        f"{MBASE}/", data=_mongo_payload(emp), content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["sql_employee_id"] == emp.id
    assert body["title"] == "Полис ДМС"
    assert body["doc_type"] == "policy"
    assert body["tags"] == ["dms"]
    assert body["metadata"] == {"year": 2026}
    assert body["created_at"] is not None
    assert body["updated_at"] is not None
    # Ровно 1 строка EmployeeDocumentBlob создана в Postgres.
    assert EmployeeDocumentBlob.objects.count() == 1


@pytest.mark.django_db
def test_get_mongo_document_invalid_id_format(auth):
    resp = Client().get(f"{MBASE}/not-a-number", **auth)
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Invalid document ID format"


@pytest.mark.django_db
def test_get_mongo_document_not_found(auth):
    assert Client().get(f"{MBASE}/999999", **auth).status_code == 404


@pytest.mark.django_db
def test_get_mongo_document_success(auth, admin_auth, emp):
    create_resp = Client().post(
        f"{MBASE}/", data=_mongo_payload(emp), content_type="application/json", **admin_auth,
    )
    doc_id = create_resp.json()["id"]
    resp = Client().get(f"{MBASE}/{doc_id}", **auth)
    assert resp.status_code == 200
    assert resp.json()["id"] == doc_id


@pytest.mark.django_db
def test_update_mongo_document_requires_admin(auth, admin_auth, emp):
    create_resp = Client().post(
        f"{MBASE}/", data=_mongo_payload(emp), content_type="application/json", **admin_auth,
    )
    doc_id = create_resp.json()["id"]
    resp = Client().patch(
        f"{MBASE}/{doc_id}", data={"title": "Новое название"},
        content_type="application/json", **auth,
    )
    assert resp.status_code == 403


@pytest.mark.django_db
def test_update_mongo_document_partial_does_not_clobber_other_fields(admin_auth, emp):
    create_resp = Client().post(
        f"{MBASE}/", data=_mongo_payload(emp), content_type="application/json", **admin_auth,
    )
    doc_id = create_resp.json()["id"]

    resp = Client().patch(
        f"{MBASE}/{doc_id}", data={"title": "Новое название"},
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["title"] == "Новое название"
    # exclude_unset — непереданные поля не затёрты.
    assert body["content"] == "текст"
    assert body["tags"] == ["dms"]
    assert body["metadata"] == {"year": 2026}
    assert body["doc_type"] == "policy"


@pytest.mark.django_db
def test_update_mongo_document_doc_type_converted_to_value(admin_auth, emp):
    create_resp = Client().post(
        f"{MBASE}/", data=_mongo_payload(emp), content_type="application/json", **admin_auth,
    )
    doc_id = create_resp.json()["id"]
    resp = Client().patch(
        f"{MBASE}/{doc_id}", data={"doc_type": "memo"},
        content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 200
    assert resp.json()["doc_type"] == "memo"


@pytest.mark.django_db
def test_update_mongo_document_not_found(admin_auth):
    resp = Client().patch(
        f"{MBASE}/999999", data={"title": "X"}, content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 404


@pytest.mark.django_db
def test_update_mongo_document_invalid_id_format(admin_auth):
    resp = Client().patch(
        f"{MBASE}/nope", data={"title": "X"}, content_type="application/json", **admin_auth,
    )
    assert resp.status_code == 400


@pytest.mark.django_db
def test_delete_mongo_document_requires_admin(auth, admin_auth, emp):
    create_resp = Client().post(
        f"{MBASE}/", data=_mongo_payload(emp), content_type="application/json", **admin_auth,
    )
    doc_id = create_resp.json()["id"]
    assert Client().delete(f"{MBASE}/{doc_id}", **auth).status_code == 403


@pytest.mark.django_db
def test_delete_mongo_document_success(admin_auth, emp):
    create_resp = Client().post(
        f"{MBASE}/", data=_mongo_payload(emp), content_type="application/json", **admin_auth,
    )
    doc_id = create_resp.json()["id"]
    resp = Client().delete(f"{MBASE}/{doc_id}", **admin_auth)
    assert resp.status_code == 204
    assert Client().get(f"{MBASE}/{doc_id}", **admin_auth).status_code == 404


@pytest.mark.django_db
def test_delete_mongo_document_not_found(admin_auth):
    assert Client().delete(f"{MBASE}/999999", **admin_auth).status_code == 404


@pytest.mark.django_db
def test_delete_mongo_document_invalid_id_format(admin_auth):
    assert Client().delete(f"{MBASE}/nope", **admin_auth).status_code == 400


# ═══════════════════════════════════════════════════════════════════════════
#  GET /employees/{id}/documents — раскрытая растяжка test_employees_api.py
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_employee_documents_forbidden_without_any_hr_access(auth, emp):
    resp = Client().get(f"{EBASE}/{emp.id}/documents", **auth)
    assert resp.status_code == 403


@pytest.mark.django_db
def test_employee_documents_missing_employee_404(admin_auth):
    resp = Client().get(f"{EBASE}/999999/documents", **admin_auth)
    assert resp.status_code == 404


@pytest.mark.django_db
def test_employee_documents_returns_desc_ordered_with_expected_shape(admin_auth, emp):
    _doc(emp, title="Первый")
    _doc(emp, title="Второй")

    resp = Client().get(f"{EBASE}/{emp.id}/documents", **admin_auth)
    assert resp.status_code == 200
    body = resp.json()
    assert [d["title"] for d in body] == ["Второй", "Первый"]
    assert set(body[0]) == {
        "id", "employee_id", "title", "doc_type", "file_path", "file_size",
        "mime_type", "metadata", "uploaded_by", "created_at", "updated_at",
    }


@pytest.mark.django_db
def test_employee_documents_empty_list_when_no_documents(admin_auth, emp):
    resp = Client().get(f"{EBASE}/{emp.id}/documents", **admin_auth)
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.django_db
def test_employee_documents_trailing_slash_variant(admin_auth, emp):
    resp = Client().get(f"{EBASE}/{emp.id}/documents/", **admin_auth)
    assert resp.status_code == 200
