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


class DocumentUploadRejected(Exception):
    """Хранилище отказало в файле (размер/mime/скоуп) — ``apps.media_files``.

    Несёт статус и текст ровно как их отдал media-слой, чтобы клиент увидел
    причину, а не общий 400 (та же схема, что ``department_file_service``).
    """

    def __init__(self, status_code: int, detail) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class EmployeeNotFound(Exception):
    """``employee_id`` не указывает на существующего сотрудника."""


def create_document_from_upload(
    token, *, employee_id: int, title: str, doc_type: str, file, description: str = "",
) -> dict:
    """Загрузка файла + карточка документа — multipart-ветка ``POST /documents/``.

    JSON-контракт исходника (``DocumentCreate``: ``file_path``/``file_size``/
    ``mime_type``/``uploaded_by`` от клиента) предполагает, что файл кто-то
    положил в хранилище заранее, — у фронта такого шага нет, он шлёт сам
    файл. Здесь ровно тот же путь, которым уже пользуется
    ``department_file_service.upload_department_file``: байты уезжают в
    ``apps.media_files`` через его ``interface`` (единственный разрешённый
    способ ходить в соседнюю аппку), а сюда сохраняется ссылка.

    ``description`` в модели колонки не имеет (её не было и в исходнике),
    поэтому вместе с id медиафайла и исходным именем кладём его в
    ``metadata`` — это JSONB, ровно для такого и заведён.

    ``uploaded_by`` заполняется карточкой сотрудника, привязанной к учётке.
    Если карточки нет (платформенный admin, интеграция) — остаётся пустым;
    авторство не теряется: id пользователя пишется в
    ``metadata["uploaded_by_user_id"]`` в любом случае.
    """
    from apps.media_files import interface as media_interface

    from apps.hr.models import Employee

    if not Employee.objects.filter(id=employee_id, is_deleted=False).exists():
        raise EmployeeNotFound

    uploader = Employee.objects.filter(
        user_id=token.user_id, is_deleted=False,
    ).first()

    try:
        stored = media_interface.store_file(
            data=file.read(),
            filename=file.name or "upload.bin",
            mime=file.content_type or "application/octet-stream",
            scope="hr_doc",
            owner_id=token.user_id,
            internal_authorized=True,
        )
    except ValueError as exc:
        status_code = getattr(exc, "status_code", 400)
        detail = getattr(exc, "detail", str(exc))
        raise DocumentUploadRejected(status_code, detail) from exc

    media_file_id = str(stored["id"])
    doc = Document.objects.create(
        employee_id=employee_id,
        title=title,
        doc_type=doc_type,
        file_path=stored.get("url") or f"/api/media/v1/files/{media_file_id}",
        file_size=int(stored.get("size") or 0),
        mime_type=stored.get("mime") or file.content_type or "application/octet-stream",
        uploaded_by_id=uploader.id if uploader else None,
        metadata={
            "media_file_id": media_file_id,
            "original_filename": stored.get("original_filename") or file.name or "",
            "description": description or "",
            "uploaded_by_user_id": token.user_id,
        },
    )
    return serialize(doc)


def patch_document(id: int, data) -> dict:
    """Частичное редактирование карточки документа (сверх контракта порта).

    Исходник правки документа не предусматривал вовсе — только create/get/
    delete. Фронт (HR → Архив) при этом всегда рисовал диалог редактирования
    и слал PUT, который упирался в 405. Добавляем ровно то, что можно
    отредактировать безопасно: название, тип и описание. Сам файл не
    трогаем — перезалить документ = загрузить новый (иначе пришлось бы
    осиротить media-файл и разъехаться с file_size/mime_type).

    ``description`` живёт в ``metadata`` (колонки под него нет — см.
    ``create_document_from_upload``), поэтому обновляем ключ точечно,
    сохраняя остальные (media_file_id, original_filename, …).
    """
    doc = get_document(id)
    payload = data.model_dump(exclude_unset=True)

    if "title" in payload and payload["title"] is not None:
        doc.title = payload["title"]
    if "doc_type" in payload and payload["doc_type"] is not None:
        doc.doc_type = payload["doc_type"]
    if "description" in payload:
        metadata = dict(doc.metadata or {})
        metadata["description"] = payload["description"] or ""
        doc.metadata = metadata

    doc.save()
    return serialize(doc)


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


# ── ex-Mongo документы (EmployeeDocumentBlob) — API снят ───────────────────
# Функции list/get/create/update/delete_mongo_document удалены вместе с
# маршрутами /mongo-documents/*: Mongo из платформы ушла, писать в таблицу
# нечем, фронт её не звал. Модель осталась — в ней могут лежать блоба,
# перенесённые разовым `manage.py etl_hr`; смотреть их можно в django-admin.
