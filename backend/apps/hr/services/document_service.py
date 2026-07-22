"""Бизнес-логика документов — порт services/hr/app/api/v1/documents.py
(+ repositories/base_repo.py в части, которую он использовал) и
services/hr/app/api/v1/mongo_documents.py (+ app/mongo.py, решение D6).

Решения, зафиксированные при переносе (docs/plans/2026-07-20-hr-domain.md,
под-модуль hr-docs):

* **Реляционные документы** (``Document``/``documents.py``): исходник НЕ
  вызывает ``require_hr_write`` НИ НА ОДНОМ эндпойнте ``documents.py`` —
  включая POST и DELETE, все 4 используют только ``get_current_user``. Это
  странность исходника (как и у recruiting/time-core, см. их докстринги),
  не баг порта: все 4 эндпойнта здесь — ``api_view(auth="jwt")`` без
  ``admin=True``.
* ``upload_document`` исходника делает
  ``data["metadata_"] = data.pop("metadata_", None)`` — самоприсваивание,
  мёртвый код (по факту не меняет ``data``). Порт просто читает
  ``metadata_`` из тела без этого промежуточного шага.
* Ни create, ни delete не проверяют, что ``employee_id``/``uploaded_by``
  указывают на существующего сотрудника, — невалидный FK падает в
  ``IntegrityError`` необработанным (буквально как у ``time_service.py``:
  исходник тоже ничего не перехватывает, SQLAlchemy отдаёт 500). Порт не
  добавляет валидацию, которой нет в контракте.
* **Mongo → PostgreSQL JSONB** (``EmployeeDocumentBlob``/``mongo_documents.py``,
  решение D6, PLAN.md §6.3): Mongo в порт не тянем — ``_require_collection``
  503-деградация исходника (пустой ``mongo_uri``) не имеет аналога здесь:
  Postgres всегда доступен, поэтому эта ветка просто отсутствует.
  ``require_hr_write`` исходника (POST/PATCH/DELETE) -> ``admin=True``; GET
  (list/single) -> обычный ``auth="jwt"``, буквально как в mongo_documents.py.
* ``doc_id`` path-параметр раньше был ObjectId (24-hex строка), теперь —
  Django integer PK. "Invalid document ID format" (400) сохраняется как код
  для НЕ-числового ``doc_id`` (тот же смысл: malformed identifier, отдельно
  от "не найден").
* ``PATCH`` c ``doc_type: null`` (явно) — исходник переписал бы Mongo-документ
  полем ``doc_type=None`` (никем не покрытая ветка, никогда не вызывается
  реальным клиентом). Колонка ``EmployeeDocumentBlob.doc_type`` — NOT NULL
  (CharField), поэтому такое значение здесь просто игнорируется (не
  затирает существующий doc_type) — не баг, defensive поведение на
  непокрытой тестами ветке исходника.
"""
from __future__ import annotations

from django.utils import timezone

from apps.hr.models import Document, EmployeeDocumentBlob


# ── реляционные документы (Document, hr_document) ──────────────────────────

class DocumentNotFound(Exception):
    """404 "Document not found" — порт документов.py::get_document/delete_document."""


def serialize(d: Document) -> dict:
    """DocumentOut (schemas/document.py)."""
    return {
        "id": d.id,
        "employee_id": d.employee_id,
        "title": d.title,
        "doc_type": d.doc_type,
        "file_path": d.file_path,
        "file_size": d.file_size,
        "mime_type": d.mime_type,
        "metadata": d.metadata,
        "uploaded_by": d.uploaded_by_id,
        "created_at": d.created_at.isoformat(),
        "updated_at": d.updated_at.isoformat(),
    }


def paginate(items: list[dict], *, total: int, page: int, limit: int) -> dict:
    """PaginatedResponse envelope — форма ТОЧНО как schemas/common.py
    (та же helper-конвенция, что recruitment_service.paginate/position_service.paginate)."""
    pages = (total + limit - 1) // limit
    return {"items": items, "total": total, "page": page, "pages": pages, "limit": limit}


def list_documents(*, page: int = 1, limit: int = 20) -> tuple[list[Document], int]:
    qs = Document.objects.order_by("-created_at")
    total = qs.count()
    offset = (page - 1) * limit
    items = list(qs[offset:offset + limit])
    return items, total


def get_document(id: int) -> Document:
    doc = Document.objects.filter(id=id).first()
    if doc is None:
        raise DocumentNotFound
    return doc


def create_document(data) -> Document:
    payload = data.model_dump(by_alias=False)
    return Document.objects.create(
        employee_id=payload["employee_id"],
        title=payload["title"],
        doc_type=payload["doc_type"],
        file_path=payload["file_path"],
        file_size=payload["file_size"],
        mime_type=payload["mime_type"],
        metadata=payload["metadata_"],
        uploaded_by_id=payload["uploaded_by"],
    )


def delete_document(id: int) -> None:
    doc = get_document(id)
    doc.delete()


def list_for_employee(employee_id: int) -> list[dict]:
    """Порт ``employees.py::employee_documents`` — GET /employees/{id}/documents.

    Исходник отдаёт ``result.scalars().all()`` БЕЗ ``response_model`` (сырые
    SQLAlchemy ORM-инстансы) — у FastAPI/Starlette это фактическая заявка на
    ``jsonable_encoder``, который для произвольного объекта без ``.dict()``
    падает на ``vars(obj)`` и рекурсивно пытается сериализовать
    ``_sa_instance_state`` (внутренности SQLAlchemy) — на непустом списке это
    почти наверняка 500 при реальном вызове (эндпойнт не покрыт НИ ОДНИМ
    тестом исходника — ни ``services/hr/tests``, ни фронтом, который на этот
    путь не ходит). Django/``htqweb.http.api_view`` не умеет и не должен
    буквально воспроизводить эту деградацию (``JsonResponse`` требует
    настоящих JSON-совместимых данных, а не бросать 500 на валидный
    список), поэтому порт возвращает те же поля, что ``DocumentOut``
    (documents.py) — рабочее поведение, которое источник, по всей видимости,
    и имел в виду, судя по остальным ``.../documents``-эндпойнтам файла
    (audit-log, history — все отдают явный список словарей).
    """
    qs = Document.objects.filter(employee_id=employee_id).order_by("-created_at")
    return [serialize(d) for d in qs]


# ── ex-Mongo документы (EmployeeDocumentBlob, hr_employeedocumentblob) ─────

def _blob_to_out(row: EmployeeDocumentBlob) -> dict:
    """HRDocumentOut (schemas/mongo_document.py) — те же ключи, что исходник.

    ``id`` — ``str(pk)`` (не ``ObjectId`` — та же СТРОКОВАЯ форма, которую
    ожидает существующий wire-контракт ``HRDocumentOut.id: str``).
    """
    data = row.data or {}
    return {
        "id": str(row.id),
        "sql_employee_id": row.employee_id,
        "title": data.get("title", ""),
        "doc_type": row.doc_type,
        "content": data.get("content", ""),
        "file_url": data.get("file_url"),
        "file_size_bytes": data.get("file_size_bytes"),
        "mime_type": data.get("mime_type", "application/octet-stream"),
        "tags": data.get("tags", []),
        "metadata": data.get("metadata", {}),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": data.get("updated_at"),
        "created_by_user_id": data.get("created_by_user_id"),
    }


def parse_blob_id(doc_id: str) -> int | None:
    """``None`` — вызывающая вьюха отвечает 400 "Invalid document ID format"
    (порт ``ObjectId(doc_id)`` / ``InvalidId`` исходника: там любой не-hex24
    id -> 400; здесь любой не-integer id -> 400, тот же смысл — malformed
    identifier)."""
    try:
        return int(doc_id)
    except (TypeError, ValueError):
        return None


def list_mongo_documents(
    *, employee_id: int | None = None, doc_type: str | None = None, page: int = 1, limit: int = 20,
) -> list[dict]:
    """Порт ``list_mongo_documents`` — БЕЗ пагинационного конверта (исходник
    отдаёт голый ``list[HRDocumentOut]``, не ``PaginatedResponse``)."""
    qs = EmployeeDocumentBlob.objects.all()
    if employee_id is not None:
        qs = qs.filter(employee_id=employee_id)
    if doc_type:
        qs = qs.filter(doc_type=doc_type)
    qs = qs.order_by("-created_at")
    offset = (page - 1) * limit
    return [_blob_to_out(row) for row in qs[offset:offset + limit]]


def get_mongo_document(doc_id: int) -> dict | None:
    row = EmployeeDocumentBlob.objects.filter(pk=doc_id).first()
    if row is None:
        return None
    return _blob_to_out(row)


def create_mongo_document(data, *, created_by_user_id: int | None) -> dict:
    now = timezone.now()
    blob = {
        "title": data.title,
        "content": data.content,
        "file_url": data.file_url,
        "file_size_bytes": data.file_size_bytes,
        "mime_type": data.mime_type,
        "tags": list(data.tags),
        "metadata": dict(data.metadata),
        "updated_at": now.isoformat(),
        "created_by_user_id": created_by_user_id,
    }
    row = EmployeeDocumentBlob.objects.create(
        employee_id=data.sql_employee_id,
        doc_type=data.doc_type.value,
        data=blob,
        created_at=now,
    )
    return _blob_to_out(row)


def update_mongo_document(doc_id: int, data) -> dict | None:
    row = EmployeeDocumentBlob.objects.filter(pk=doc_id).first()
    if row is None:
        return None

    patch = data.model_dump(exclude_unset=True)
    doc_type = patch.pop("doc_type", ...)  # ... = "ключ отсутствовал"
    if doc_type not in (..., None):
        row.doc_type = doc_type.value

    blob = dict(row.data or {})
    for key, value in patch.items():
        blob[key] = value
    blob["updated_at"] = timezone.now().isoformat()
    row.data = blob
    row.save(update_fields=["doc_type", "data"])
    return _blob_to_out(row)


def delete_mongo_document(doc_id: int) -> bool:
    deleted, _ = EmployeeDocumentBlob.objects.filter(pk=doc_id).delete()
    return deleted > 0
