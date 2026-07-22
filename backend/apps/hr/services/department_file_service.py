"""Department File Manager — порт services/hr/app/api/v1/department_files.py.

Файловые байты — через ``apps.media_files.interface.store_file`` (scope
``hr_department``), не через httpx-проксирование к отдельному media-service
(исходник — ещё FastAPI-микросервисная топология). ``hr_department`` в
``apps.media_files.services.scope_policy.RESTRICTED_SCOPES`` — вызывающий
обязан явно поручиться (``internal_authorized=True``), что уже прогнал
собственную ролевую проверку; здесь это ``assert_department_access`` НИЖЕ по
стеку ПЕРЕД вызовом ``store_file`` — тот самый "внутренний доверенный
потребитель", о котором говорит докстринг ``store_file`` (docs/plans/
2026-07-20-hr-domain.md, D8).

Функции, а не класс — та же конвенция порта, что department_service.py и
share_link_service.py (исходный роутер был module-level функциями с function
DI, а не классом).

Сознательно НЕ портируется (см. отчёт):
- httpx-специфичные 502 "media-service unavailable"/"media-service returned
  invalid JSON" — в in-process вызове через apps.media_files.interface этот
  класс отказов структурно невозможен (нет сети между hr и media в
  Django-монолите).
- Явная проверка заголовка Authorization внутри ``_upload_to_media`` —
  избыточна здесь: ``api_view(auth="jwt")`` уже гарантирует валидный JWT ДО
  вызова вьюхи; ``request.token`` не бывает None на этом пути.
- ``session.commit()`` перед outbound-вызовом (освобождение пула соединений
  перед сетевым I/O) — Django ORM не держит пул соединений так же, как
  asyncpg/SQLAlchemy; в in-process вызове нет отдельного сетевого запроса,
  которого нужно было бы дожидаться.
- Redis pub/sub-уведомление messenger-бота "Файлы" (``notify.
  file_access_request``) о новом файле отдела — тот же класс решений, что
  дропнутый dramatiq (Р2 плана): подписчика этого канала в Django-монолите
  ещё нет, публикация в пустоту не имеет наблюдаемого эффекта.
"""
from __future__ import annotations

from django.db.models import Count, Q

from apps.hr.models import Department, DepartmentFile, DepartmentFileFolder, Employee


class DepartmentNotFound(Exception):
    """404 "Department not found"."""


class DepartmentAccessDenied(Exception):
    """403 "Department access denied"."""


class FileFolderNotFound(Exception):
    """404 "File folder not found"."""


class FolderNameRequired(Exception):
    """400 "Folder name is required"."""


class FolderAlreadyExists(Exception):
    """409 "Folder already exists"."""


class DepartmentFileNotFound(Exception):
    """404 "Department file not found"."""


class UploadRejected(Exception):
    """Пайплайн загрузки media_files отверг файл — оборачивает
    ``ValueError``-совместимый ``UploadValidationError`` соседней аппки
    (status_code/detail) БЕЗ прямого импорта её класса — прямой импорт чего-
    либо, кроме ``apps.media_files.interface``, ловится
    apps/core/tests/test_app_isolation.py. ``UploadValidationError`` —
    подкласс встроенного ``ValueError`` (не app-специфичный тип), поэтому
    ``except ValueError`` в ``upload_department_file`` ниже ловит его по
    duck-typing атрибутов ``status_code``/``detail``, не по импорту класса.
    """

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


def is_admin(token) -> bool:
    return bool(token.is_elevated)


def employee_for_user(token) -> Employee | None:
    if token.user_id is None:
        return None
    return Employee.objects.filter(user_id=token.user_id, is_deleted=False).first()


def assert_department_access(token, department_id: int) -> Department:
    department = Department.objects.filter(id=department_id).first()
    if department is None or not department.is_active:
        raise DepartmentNotFound
    if is_admin(token):
        return department
    employee = employee_for_user(token)
    if employee is None or employee.department_id != department_id:
        raise DepartmentAccessDenied
    return department


def assert_file_folder_access(
    token, file_folder_id: int, *, department_id: int | None = None,
) -> DepartmentFileFolder:
    file_folder = DepartmentFileFolder.objects.filter(id=file_folder_id).first()
    if file_folder is None:
        raise FileFolderNotFound
    if department_id is not None and file_folder.department_id != department_id:
        raise FileFolderNotFound
    assert_department_access(token, file_folder.department_id)
    return file_folder


def _employee_display_name(employee: Employee | None, token) -> str | None:
    if employee is not None:
        full_name = " ".join(p for p in [employee.first_name, employee.last_name] if p)
        if full_name:
            return full_name
    return token.username or token.email


def _normalize_folder_name(name: str) -> str:
    normalized = " ".join(name.strip().split())
    if not normalized:
        raise FolderNameRequired
    return normalized


def _to_file_folder_out(row: DepartmentFileFolder, files_count: int = 0) -> dict:
    return {
        "id": row.id,
        "department": row.department_id,
        "name": row.name,
        "files_count": files_count,
        "created_by": row.created_by_user_id,
        "created_by_name": row.created_by_name,
        "created_at": row.created_at.isoformat(),
    }


def _to_file_out(row: DepartmentFile) -> dict:
    return {
        "id": row.id,
        "folder": row.department_id,
        "file_folder": row.file_folder_id,
        "name": row.name,
        "file": row.file_url,
        "file_url": row.file_url,
        "file_size": row.file_size,
        "uploaded_by": row.uploaded_by_user_id,
        "uploaded_by_name": row.uploaded_by_name,
        "description": row.description,
        "created_at": row.created_at.isoformat(),
    }


def list_department_folders(token) -> list[dict]:
    qs = Department.objects.filter(is_active=True).order_by("name")
    if not is_admin(token):
        employee = employee_for_user(token)
        if employee is None:
            return []
        qs = qs.filter(id=employee.department_id)

    departments = list(qs)
    if not departments:
        return []

    counts_qs = (
        DepartmentFile.objects.filter(department_id__in=[d.id for d in departments])
        .values("department_id")
        .annotate(n=Count("id"))
    )
    counts = {row["department_id"]: row["n"] for row in counts_qs}

    return [
        {
            "id": d.id,
            "department": d.id,
            "department_name": d.name,
            "files_count": int(counts.get(d.id, 0)),
            "created_at": d.created_at.isoformat(),
        }
        for d in departments
    ]


def accessible_department_ids(token) -> list[int] | None:
    """Отделы, которые вызывающий вправе просматривать, или ``None`` = "все" (admin)."""
    if is_admin(token):
        return None
    employee = employee_for_user(token)
    if employee is None or employee.department_id is None:
        return []
    return [employee.department_id]


def search_department_files(token, q: str, *, limit: int = 20) -> list[dict]:
    department_ids = accessible_department_ids(token)
    if department_ids is not None and not department_ids:
        return []

    pattern = q.strip()
    qs = DepartmentFile.objects.filter(
        Q(name__icontains=pattern) | Q(description__icontains=pattern)
    ).order_by("-created_at")
    if department_ids is not None:
        qs = qs.filter(department_id__in=department_ids)

    return [_to_file_out(row) for row in qs[:limit]]


def list_department_file_folders(token, department_id: int) -> list[dict]:
    assert_department_access(token, department_id)
    folders = list(
        DepartmentFileFolder.objects.filter(department_id=department_id).order_by("name")
    )
    if not folders:
        return []

    counts_qs = (
        DepartmentFile.objects.filter(file_folder_id__in=[f.id for f in folders])
        .values("file_folder_id")
        .annotate(n=Count("id"))
    )
    counts = {row["file_folder_id"]: row["n"] for row in counts_qs}
    return [_to_file_folder_out(f, int(counts.get(f.id, 0))) for f in folders]


def create_department_file_folder(token, department_id: int, name: str) -> dict:
    assert_department_access(token, department_id)
    normalized = _normalize_folder_name(name)

    exists = DepartmentFileFolder.objects.filter(
        department_id=department_id, name__iexact=normalized,
    ).exists()
    if exists:
        raise FolderAlreadyExists

    employee = employee_for_user(token)
    row = DepartmentFileFolder.objects.create(
        department_id=department_id,
        name=normalized,
        created_by_user_id=token.user_id,
        created_by_name=_employee_display_name(employee, token),
    )
    return _to_file_folder_out(row, 0)


def list_department_files(
    token, *, folder: int, file_folder: int | None = None, root_only: bool = False,
) -> list[dict]:
    assert_department_access(token, folder)
    qs = DepartmentFile.objects.filter(department_id=folder)
    if file_folder is not None:
        assert_file_folder_access(token, file_folder, department_id=folder)
        qs = qs.filter(file_folder_id=file_folder)
    elif root_only:
        qs = qs.filter(file_folder_id__isnull=True)

    return [_to_file_out(row) for row in qs.order_by("-created_at")]


def upload_department_file(
    token, *, folder: int, file_folder: int | None, file, description: str = "",
) -> dict:
    assert_department_access(token, folder)
    if file_folder is not None:
        assert_file_folder_access(token, file_folder, department_id=folder)

    from apps.media_files import interface as media_interface

    try:
        result = media_interface.store_file(
            data=file.read(),
            filename=file.name or "upload.bin",
            mime=file.content_type or "application/octet-stream",
            scope="hr_department",
            owner_id=token.user_id,
            internal_authorized=True,
        )
    except ValueError as exc:
        status_code = getattr(exc, "status_code", 400)
        detail = getattr(exc, "detail", str(exc))
        raise UploadRejected(status_code, detail) from exc

    employee = employee_for_user(token)
    row = DepartmentFile.objects.create(
        department_id=folder,
        file_folder_id=file_folder,
        media_file_id=str(result["id"]),
        name=result.get("original_filename") or file.name or "upload.bin",
        file_url=result.get("url") or f"/api/media/v1/files/{result['id']}",
        file_size=int(result.get("size") or 0),
        mime_type=result.get("mime") or file.content_type or "application/octet-stream",
        uploaded_by_user_id=token.user_id,
        uploaded_by_name=_employee_display_name(employee, token),
        description=description or "",
    )
    return _to_file_out(row)


def delete_department_file(token, file_id: int) -> None:
    row = DepartmentFile.objects.filter(id=file_id).first()
    if row is None:
        raise DepartmentFileNotFound
    assert_department_access(token, row.department_id)
    row.delete()
