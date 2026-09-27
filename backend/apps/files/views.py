"""HTTP — ``/api/files/v1/*`` (ТЗ стр. 68: ``UploadFile`` / ``DownloadFile``).

Вьюхи тонкие: разобрать запрос → позвать ``services.documents`` → отдать
ответ. Отказы подсистемы — в конверте D-28 (``FilesError`` → ``{detail, code,
fields, details}``); 401 (нет токена), 403 несовпадения компании токена и
503 (выключен сервис) остаются общими ответами ``api_view`` — это отказы
платформы, а не подсистемы.

Загрузка — multipart без ``body=`` (тот разбирает JSON). Права проверяются
ДО ``request.FILES`` (``documents.precheck``): разбор multipart и чтение
файла в память не должны доставаться тому, кому всё равно ответят 404/403.

Каждый маршрут — через диспетчер по методу: неподдерживаемый метод получает
405 в конверте D-28, а не общий ответ ``api_view``. Диспетчеры — голые цепочки
``if request.method == …: return <ручка>(…)``: только такую форму сторож прав
(``apps/access/tests/test_gate.py``) признаёт закрытой — никакого кода до
гейта ручки.
"""

from __future__ import annotations

import json
from functools import wraps

from django.core.exceptions import SuspiciousOperation
from django.http import HttpResponse, JsonResponse
from django.http.multipartparser import MultiPartParserError

from apps.core.infrastructure import client_ip
from htqweb.http import api_view

from .errors import E_BAD_REQUEST, FilesError, bad_request, envelope
from .services import documents


def files_errors(fn):
    """Отказы подсистемы — в формате ТЗ. Сюда же — битый multipart и
    запрос сверх лимитов Django (слишком много полей, тело больше
    допустимого): иначе первое стало бы 500, второе — общим 400."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except FilesError as exc:
            return exc.response()
        except (MultiPartParserError, SuspiciousOperation):
            return bad_request(
                "Запрос повреждён или слишком велик. Обновите страницу и повторите "
                "загрузку.").response()
    return wrapper


def _method_not_allowed(request):
    return JsonResponse(envelope(
        E_BAD_REQUEST,
        f"Метод {request.method} здесь не поддерживается.",
        details={"method": request.method}), status=405)


def _audit(request) -> dict:
    """Кто и откуда — для журнала файловых операций (ТЗ §25.2: IP и
    user-agent). IP — по той же схеме, что остальной аудит платформы."""
    return {"ip": client_ip(request) or "",
            "user_agent": request.META.get("HTTP_USER_AGENT", "")[:300]}


# ── папка владельца ─────────────────────────────────────────────────────

@api_view(methods=("GET",))
@files_errors
def _folder_get(request, owner_type: str, owner_id: str):
    return documents.folder(owner_type, owner_id, request.token)


def _attach(request, owner_type: str, owner_id: str, document_id=None):
    ref = documents.precheck(owner_type, owner_id, request.token,
                             document_id=document_id)
    row = documents.upload(
        ref, request.token,
        upload=request.FILES.get("file"),
        file_type=request.POST.get("file_type"),
        document_id=document_id,
        base_file_id=request.POST.get("base_file_id"),
        idempotency_key=request.headers.get("Idempotency-Key", ""),
        audit=_audit(request),
    )
    return documents.version_out(row)


@api_view(methods=("POST",), status=201)
@files_errors
def _folder_post(request, owner_type: str, owner_id: str):
    return _attach(request, owner_type, owner_id)


def owner_files(request, owner_type: str, owner_id: str):
    if request.method == "GET":
        return _folder_get(request, owner_type=owner_type, owner_id=owner_id)
    if request.method == "POST":
        return _folder_post(request, owner_type=owner_type, owner_id=owner_id)
    return _method_not_allowed(request)


@api_view(methods=("POST",), status=201)
@files_errors
def _versions_post(request, owner_type: str, owner_id: str, document_id):
    return _attach(request, owner_type, owner_id, document_id=document_id)


def document_versions(request, owner_type: str, owner_id: str, document_id):
    if request.method == "POST":
        return _versions_post(request, owner_type=owner_type, owner_id=owner_id,
                              document_id=document_id)
    return _method_not_allowed(request)


@api_view(methods=("DELETE",))
@files_errors
def _document_delete(request, owner_type: str, owner_id: str, document_id):
    documents.delete(owner_type, owner_id, document_id, request.token,
                     audit=_audit(request))
    return HttpResponse(status=204)


def document_detail(request, owner_type: str, owner_id: str, document_id):
    if request.method == "DELETE":
        return _document_delete(request, owner_type=owner_type, owner_id=owner_id,
                                document_id=document_id)
    return _method_not_allowed(request)


@api_view(methods=("GET",))
@files_errors
def _link_get(request, owner_type: str, owner_id: str, document_id, file_id: int):
    return documents.link(owner_type, owner_id, document_id, file_id, request.token,
                          audit=_audit(request))


def version_link(request, owner_type: str, owner_id: str, document_id, file_id: int):
    if request.method == "GET":
        return _link_get(request, owner_type=owner_type, owner_id=owner_id,
                         document_id=document_id, file_id=file_id)
    return _method_not_allowed(request)


# ── справочник «Типы файлов» ────────────────────────────────────────────

@api_view(methods=("GET",))
@files_errors
def _types_get(request):
    return documents.types_list(request.GET.get("owner_type") or None)


def types_collection(request):
    if request.method == "GET":
        return _types_get(request)
    return _method_not_allowed(request)


# Гейт модуля: права — только через apps.access (мастер-план БЗО, §3). Узел
# ``files.types`` несёт view/edit, правка размера — ``write``. Отказ гейта —
# общий ответ платформы (403 ``{"detail"}``), как 401 и 503.
@api_view(methods=("PATCH",), module="files", level="write")
@files_errors
def _type_patch(request, code: str):
    # Тело разбирается здесь, а не через body=: отказ валидации должен быть
    # в формате ТЗ, а не в общем 422 api_view.
    try:
        data = json.loads(request.body or b"{}")
    except ValueError:
        raise bad_request("Тело запроса — не JSON. Обновите страницу и повторите.") from None
    if not isinstance(data, dict):
        raise bad_request("Ожидается объект {\"max_mb\": …}.", field="max_mb")
    return documents.types_update(code, data.get("max_mb"), request.token)


def type_detail(request, code: str):
    if request.method == "PATCH":
        return _type_patch(request, code=code)
    return _method_not_allowed(request)
