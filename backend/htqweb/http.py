"""API-слой на встроенном ядре Django.

Воспроизводит контракт FastAPI (envelope {"detail": ...}, коды 401/405/422/500)
поверх обычных Django-вьюх. Pydantic-схемы аппок используются как есть.
Путь на django-ninja (см. план §7): schemas/services не меняются, заменяется
только этот модуль и объявления в views/urls.
"""
import json
import logging
from functools import wraps

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from pydantic import BaseModel, ValidationError

from htqweb.authn.jwt import AuthError, decode_token


def json_error(detail, status: int) -> JsonResponse:
    return JsonResponse({"detail": detail}, status=status)


def _authenticate_jwt(request):
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return None
    try:
        payload = decode_token(header[7:])
    except (AuthError, ValidationError):
        return None
    return payload if payload.token_type == "access" else None


def _authenticate_admin_session(request):
    raw = request.COOKIES.get("admin_session")
    if not raw:
        return None
    try:
        payload = decode_token(raw)
    except (AuthError, ValidationError):
        return None
    return payload if payload.is_elevated else None


_AUTHENTICATORS = {"jwt": _authenticate_jwt,
                   "admin_session": _authenticate_admin_session}


def api_view(methods=("GET",), auth="jwt", body: type[BaseModel] | None = None):
    def deco(fn):
        @csrf_exempt
        @wraps(fn)
        def view(request, *args, **kwargs):
            if request.method not in methods:
                return json_error("Method Not Allowed", 405)
            if auth is not None:
                payload = _AUTHENTICATORS[auth](request)
                if payload is None:
                    return json_error("Not authenticated", 401)
                request.token = payload
            if body is not None:
                try:
                    kwargs["data"] = body.model_validate_json(request.body or b"{}")
                except ValidationError as exc:
                    return JsonResponse({"detail": json.loads(exc.json())},
                                        status=422)
            try:
                result = fn(request, *args, **kwargs)
                if isinstance(result, BaseModel):
                    return JsonResponse(result.model_dump(mode="json"))
                if isinstance(result, (dict, list)):
                    return JsonResponse(result, safe=False)
                return result  # готовый HttpResponse (файлы, 302, кастомные статусы)
            except Exception:  # контракт: 500 всегда в envelope
                logging.getLogger("htqweb").exception("unhandled API error")
                return json_error("Internal Server Error", 500)
        return view
    return deco
