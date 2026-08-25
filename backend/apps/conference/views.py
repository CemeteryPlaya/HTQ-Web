"""HTTP-слой аппки conference.

Две группы маршрутов с РАЗНОЙ аутентификацией:

* ``internal/*`` — канал SFU → Django. ``auth=None`` + общий секрет первой
  строкой каждой вьюхи (``services.internal_auth.require_internal``).
* всё остальное — обычный платформенный JWT, поверх которого стоит
  ``services.access`` («участники встречи + админы»).

Вьюхи тонкие: разобрать параметры → позвать сервис → отдать схему.
"""

from __future__ import annotations

from datetime import date

from django.http import Http404, HttpResponse, HttpResponseRedirect
from django.utils import timezone

from apps.core.services import require_service
from htqweb.http import _authenticate_jwt, api_view, json_error

from . import schemas
from .models import ConferenceSession, RecordingState
from .services import access, history_service, internal_auth, overview_service, session_service
from .services import signing, storage_service


# ── query-параметры ────────────────────────────────────────────────────────
# Те же хелперы и тот же вид 422, что в apps/tasks/views.py — контракт
# ошибок у платформы один, и списки истории не должны отвечать иначе, чем
# остальные списки.

class _ParamError(Exception):
    def __init__(self, response):
        self.response = response


def _param_error(name: str, message: str):
    return json_error(
        [{"type": "value_error", "loc": ["query", name], "msg": message}], 422,
    )


def _int_param(request, name: str, default=None, *, minimum=None, maximum=None):
    raw = request.GET.get(name)
    if raw in (None, ""):
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise _ParamError(_param_error(name, "Input should be a valid integer"))
    if minimum is not None and value < minimum:
        raise _ParamError(_param_error(
            name, f"Input should be greater than or equal to {minimum}"))
    if maximum is not None and value > maximum:
        raise _ParamError(_param_error(
            name, f"Input should be less than or equal to {maximum}"))
    return value


def _date_param(request, name: str):
    raw = request.GET.get(name)
    if raw in (None, ""):
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise _ParamError(_param_error(
            name, "Input should be a valid date in YYYY-MM-DD format"))


def _bool_param(request, name: str, default: bool = False) -> bool:
    raw = request.GET.get(name)
    if raw in (None, ""):
        return default
    return raw.lower() in ("1", "true", "yes", "on")


# ── Публичные маршруты ─────────────────────────────────────────────────────


@api_view(methods=("GET",))
def overview(request):
    """Сегодняшние и идущие сейчас встречи этого пользователя."""
    require_service("conference")
    return overview_service.build(request)


@api_view(methods=("GET",))
def sessions(request):
    """История встреч, доступных этому пользователю."""
    require_service("conference")
    try:
        page = _int_param(request, "page", 1, minimum=1)
        limit = _int_param(request, "limit", 25, minimum=1, maximum=100)
        date_from = _date_param(request, "from")
        date_to = _date_param(request, "to")
    except _ParamError as exc:
        return exc.response

    return history_service.list_sessions(
        request, page=page, limit=limit,
        query=(request.GET.get("q") or "").strip(),
        date_from=date_from, date_to=date_to,
        mine=_bool_param(request, "mine"),
    )


@api_view(methods=("GET",))
def session_detail(request, session_id: int):
    require_service("conference")
    session = access.get_visible_session(session_id, request)
    return history_service.session_detail(session)


@api_view(methods=("GET",))
def session_events(request, session_id: int):
    require_service("conference")
    session = access.get_visible_session(session_id, request)
    return [schemas.EventRead.model_validate(event)
            for event in session.events.all()]


@api_view(methods=("GET",))
def session_transcript(request, session_id: int):
    """Протокол: JSON для интерфейса, txt/md — для выгрузки."""
    require_service("conference")
    session = access.get_visible_session(session_id, request)

    fmt = (request.GET.get("format") or "json").lower()
    if fmt == "json":
        return history_service.transcript(session)
    if fmt not in ("txt", "md"):
        return _param_error("format", "Input should be 'json', 'txt' or 'md'")

    body, mime, filename = history_service.render_transcript(session, fmt)
    response = HttpResponse(body.encode("utf-8"), content_type=mime)
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


class _Unauthenticated(Exception):
    """Ни подписи, ни токена. Несёт готовый 401, как ``_ParamError`` — 422."""

    response = None

    def __init__(self):
        super().__init__("not authenticated")
        self.response = json_error("Not authenticated", 401)


def _authorize_media(session_id: int, kind: str, request) -> ConferenceSession:
    """Впустить по подписи ``?sig=&exp=`` либо по обычному JWT.

    Две двери в одну комнату, потому что у клиентов разные возможности.
    ``<video src>`` заголовок Authorization не отправляет — для него
    единственный способ это подпись, выданная карточкой встречи после
    проверки прав (services/signing.py). Обычный API-клиент, наоборот, ходит
    с токеном и подписи не имеет.

    ⚠️ Токен здесь разбирается ВРУЧНУЮ, и это обязательно: вьюха объявлена
    ``api_view(auth=None)`` (иначе плеер без Authorization получал бы 401 и
    до подписи дело не доходило), а при ``auth=None`` декоратор кладёт в
    ``request.token`` None и заголовок не смотрит вовсе. Без этой строки
    вторая дверь была бы нарисованной: даже верный токен упирался бы в
    ``may_view`` с пустым ``request.token`` и получал 404.
    """
    if signing.signature_ok(kind, session_id, request):
        session = ConferenceSession.objects.filter(pk=session_id).first()
        if session is None:
            raise Http404("Конференция не найдена")
        return session

    if getattr(request, "token", None) is None:
        request.token = _authenticate_jwt(request)
    if request.token is None:
        raise _Unauthenticated()

    return access.get_visible_session(session_id, request)


def _redirect_to_object(session: ConferenceSession, recording, *,
                        download_as: str | None = None):
    if recording is None:
        return json_error("Запись недоступна", 404)
    return HttpResponseRedirect(
        storage_service.playback_url(recording.storage_path, download_as=download_as),
    )


@api_view(methods=("GET",), auth=None)
def session_recording(request, session_id: int):
    """302 на свежую временную ссылку хранилища.

    Редирект, а не отдача байтов через Django: только так у ``<video>``
    остаётся Range, то есть перемотка по часовой записи. Вариант «прочитать
    файл и вернуть HttpResponse» тянет его целиком в память и перемотку
    убивает.

    ``auth=None`` не означает «без защиты»: доступ проверяет
    ``_authorize_media`` — подписью или токеном.
    """
    require_service("conference")
    try:
        session = _authorize_media(session_id, signing.RECORDING, request)
    except _Unauthenticated as exc:
        return exc.response

    if session.recording_state == RecordingState.PURGED:
        return json_error("Запись удалена по сроку хранения", 404)

    download_as = None
    if _bool_param(request, "download"):
        stamp = session.started_at.strftime("%Y-%m-%d_%H-%M")
        download_as = f"conference-{session.pk}-{stamp}.mp4"

    return _redirect_to_object(session, history_service.composed_recording(session),
                               download_as=download_as)


@api_view(methods=("GET",), auth=None)
def session_poster(request, session_id: int):
    """Кадр-заставка карточки. Та же схема доступа, что у записи."""
    require_service("conference")
    try:
        session = _authorize_media(session_id, signing.POSTER, request)
    except _Unauthenticated as exc:
        return exc.response
    return _redirect_to_object(session, history_service.poster_recording(session))


# ── Внутренний канал: SFU → Django ─────────────────────────────────────────


@api_view(methods=("POST",), auth=None, body=schemas.InternalSessionStart)
def internal_session_start(request, data: schemas.InternalSessionStart):
    internal_auth.require_internal(request)
    require_service("conference")

    session = session_service.start_session(
        room_id=data.room_id,
        started_at=data.started_at,
        created_by_id=data.created_by_id,
        created_by_name=data.created_by_name,
        title=data.title,
    )
    return schemas.InternalSessionStarted(
        session_id=session.pk,
        started_at=session.started_at,
        recording_enabled=session.recording_state == RecordingState.RECORDING,
        raw_dir=str(session.pk),
    )


def _open_session_or_404(session_id: int) -> ConferenceSession:
    from django.http import Http404

    session = ConferenceSession.objects.filter(pk=session_id).first()
    if session is None:
        raise Http404("Конференция не найдена")
    return session


@api_view(methods=("POST",), auth=None, body=schemas.InternalParticipant)
def internal_participant(request, session_id: int, data: schemas.InternalParticipant):
    internal_auth.require_internal(request)
    require_service("conference")

    session = _open_session_or_404(session_id)
    if data.action == "leave":
        session_service.participant_left(session, peer_id=data.peer_id, left_at=data.at)
    else:
        session_service.participant_joined(
            session, peer_id=data.peer_id, display_name=data.display_name,
            user_id=data.user_id, is_guest=data.is_guest, joined_at=data.at,
        )
    return schemas.InternalAck(session_id=session.pk)


@api_view(methods=("POST",), auth=None, body=schemas.InternalEvent)
def internal_event(request, session_id: int, data: schemas.InternalEvent):
    internal_auth.require_internal(request)
    require_service("conference")

    session = _open_session_or_404(session_id)
    participant = None
    if data.peer_id:
        participant = session.participants.filter(peer_id=data.peer_id).first()
    session_service.log_event(session, kind=data.kind, at_ms=data.at_ms,
                              participant=participant, payload=data.payload)
    return schemas.InternalAck(session_id=session.pk)


@api_view(methods=("POST",), auth=None, body=schemas.InternalArtifacts)
def internal_artifacts(request, session_id: int, data: schemas.InternalArtifacts):
    """Рекордер сообщает о дописанных на том дорожках.

    Отдельно от ``finish``, потому что дорожка закрывается в момент, когда
    участник выключил камеру или вышел, — то есть задолго до конца встречи.
    Сообщать о ней сразу надёжнее: если SFU упадёт, до сборки доживёт всё,
    о чём он успел рассказать.
    """
    internal_auth.require_internal(request)
    require_service("conference")

    session = _open_session_or_404(session_id)
    session_service.register_artifacts(session, data.artifacts)
    return schemas.InternalAck(session_id=session.pk)


@api_view(methods=("POST",), auth=None, body=schemas.InternalSessionFinish)
def internal_session_finish(request, session_id: int,
                            data: schemas.InternalSessionFinish):
    internal_auth.require_internal(request)
    require_service("conference")

    session = _open_session_or_404(session_id)
    if data.artifacts:
        session_service.register_artifacts(session, data.artifacts)
    session_service.finish_session(session, ended_at=data.ended_at or timezone.now())
    return schemas.InternalAck(session_id=session.pk)
