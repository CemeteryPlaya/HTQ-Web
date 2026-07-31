"""API-слой на встроенном ядре Django.

Воспроизводит контракт FastAPI (envelope {"detail": ...}, коды 401/405/422/500)
поверх обычных Django-вьюх. Pydantic-схемы аппок используются как есть.
Путь на django-ninja (см. план §7): schemas/services не меняются, заменяется
только этот модуль и объявления в views/urls.
"""
import logging
from functools import wraps

from django.core.exceptions import PermissionDenied, SuspiciousOperation
from django.http import Http404, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from pydantic import BaseModel, ValidationError

from apps.core.services import ServiceDisabled, disabled_payload
from htqweb.authn.jwt import AuthError, decode_token
from htqweb.authn.rbac import require_admin


def json_error(detail, status: int) -> JsonResponse:
    return JsonResponse({"detail": detail}, status=status)


def validation_detail(exc: ValidationError) -> list[dict]:
    """Ошибки валидации тела в JSON-безопасном виде.

    Раньше здесь стоял ``json.loads(exc.json())``, и он ронял ответ. В
    записи об ошибке pydantic держит поле ``input`` — исходное значение так,
    как он его увидел. Для тела, разобранного из ``bytes``, это срез
    исходных байтов, и на любом не-ASCII символе срез рвётся посередине
    UTF-8 последовательности. ``exc.json()`` на таком падает с
    ``ValueError``, причём падает ПРЯМО В обработчике ошибки — внешний
    ``except`` его не ловит, и клиент вместо 422 получает голый 500.

    На практике это означало: любая форма с русским текстом, где хоть одно
    поле не прошло валидацию, отвечала 500 без единого слова о том, что не
    так. Воспроизводилось на ``applications/``, ``departments/``,
    ``vacancies/`` — то есть на всех аппах разом, потому что живёт здесь.

    ``exc.errors()`` возвращает те же записи обычными объектами Python и
    ничего не сериализует. ``input`` из них выбрасывается намеренно: клиент
    и так знает, что отправил, ``loc`` называет место, а возвращать телу
    запроса эхо — лишний способ утащить в лог то, чему там не место.
    Форма ``{"type", "loc", "msg"}`` совпадает с той, что вьюхи собирают
    руками для своих 422 (см. ``_param_error`` в apps/tasks/views.py).
    """
    return [
        {
            "type": err.get("type", "value_error"),
            "loc": list(err.get("loc", ())),
            "msg": err.get("msg", "Invalid value"),
        }
        for err in exc.errors(include_url=False)
    ]


def _authenticate_jwt(request):
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return None
    try:
        payload = decode_token(header[7:])
    except (AuthError, ValidationError):
        return None
    return payload if payload.token_type == "access" else None


_AUTHENTICATORS = {"jwt": _authenticate_jwt}


def api_view(methods=("GET",), auth="jwt", body: type[BaseModel] | None = None,
            status: int = 200, admin: bool = False):
    if admin and auth is None:
        # admin=True checks request.token, which only an authenticator
        # populates — auth=None always sets it to None (see below), so the
        # admin predicate would have nothing to check. Programming error:
        # fail loudly at decoration time, not as a confusing 403 later.
        raise ValueError("api_view(admin=True) requires auth='jwt'")

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
                # Single platform admin-gate seam (R1): every admin route
                # goes through this one predicate — htqweb.authn.rbac.
                # require_admin — instead of each app keeping its own
                # private _require_admin copy.
                if admin and not require_admin(request.token):
                    return json_error("Forbidden", 403)
            else:
                request.token = None  # чтобы вьюхи с auth=None не падали на AttributeError
            if body is not None:
                try:
                    kwargs["data"] = body.model_validate_json(request.body or b"{}")
                except ValidationError as exc:
                    return JsonResponse({"detail": validation_detail(exc)},
                                        status=422)
            try:
                result = fn(request, *args, **kwargs)
                if isinstance(result, BaseModel):
                    return JsonResponse(result.model_dump(mode="json"), status=status)
                if isinstance(result, list) and result and all(isinstance(item, BaseModel) for item in result):
                    return JsonResponse(
                        [item.model_dump(mode="json") for item in result], safe=False, status=status,
                    )
                if isinstance(result, (dict, list)):
                    return JsonResponse(result, safe=False, status=status)
                return result  # готовый HttpResponse (файлы, 302, кастомные статусы) — status игнорируется
            except ServiceDisabled as exc:
                # require_service() у выключенного соседа — та же 503-envelope,
                # что и внешний HTTP-гейт (ServiceGateMiddleware), иначе
                # межаппная деградация видна как голый 500.
                return JsonResponse(disabled_payload(exc.service, exc.message), status=503)
            except Http404 as exc:
                detail = str(exc) or "Not Found"
                return json_error(detail, 404)
            except PermissionDenied:
                return json_error("Forbidden", 403)
            except SuspiciousOperation:
                return json_error("Bad Request", 400)
            except Exception:  # контракт: 500 всегда в envelope
                logging.getLogger("htqweb").exception("unhandled API error")
                return json_error("Internal Server Error", 500)
        return view
    return deco
