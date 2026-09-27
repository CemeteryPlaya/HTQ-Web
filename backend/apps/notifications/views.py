"""Ручки центра уведомлений — самообслуживание (свои уведомления и каналы).

Под гейтом модуля их нет намеренно: лента нужна каждому вошедшему, включая
держателей ролей без единого узла (записи ``self`` в
``apps/access/self_service.py``). Получатель — всегда ``request.token.user_id``.
Вебхук Telegram — ``auth=None``, защищён секретом бота.
"""

from __future__ import annotations

import json

from django.http import HttpResponse

from htqweb.errors import DomainError
from htqweb.http import api_view, json_error

from . import interface, schemas
from .models import ChannelPrefs
from .services import center, telegram


def _company(request):
    return (getattr(request, "company", None) or {}).get("slug")


class _BadParam(Exception):
    pass


def _int_param(request, name: str, default: int, low: int, high: int) -> int:
    """Целый параметр запроса в пределах ``[low, high]``; не число — 422."""
    raw = request.GET.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        raise _BadParam(f"Параметр «{name}» должен быть целым числом.") from None
    return max(low, min(value, high))


@api_view(methods=("GET",))
def feed(request):
    try:
        limit = _int_param(request, "limit", 50, 1, 200)
    except _BadParam as exc:
        return json_error(str(exc), 422)
    return interface.latest(request.token.user_id, company_slug=_company(request),
                            limit=limit)


@api_view(methods=("GET",))
def feed_history(request):
    try:
        page = _int_param(request, "page", 1, 1, 10_000)
        limit = _int_param(request, "limit", 25, 1, 100)
    except _BadParam as exc:
        return json_error(str(exc), 422)
    return interface.history(request.token.user_id, company_slug=_company(request),
                             page=page, limit=limit,
                             status=request.GET.get("status", "all"),
                             target_type=request.GET.get("target_type") or None)


@api_view(methods=("POST",))
def read_one(request, notification_id: str):
    interface.mark_read(notification_id, request.token.user_id)
    return HttpResponse(status=204)


@api_view(methods=("POST",))
def unread_one(request, notification_id: str):
    interface.mark_unread(notification_id, request.token.user_id)
    return HttpResponse(status=204)


@api_view(methods=("POST",))
def read_all(request):
    interface.mark_all_read(request.token.user_id, company_slug=_company(request))
    return HttpResponse(status=204)


@api_view(methods=("DELETE",))
def delete_one(request, notification_id: str):
    interface.delete(notification_id, request.token.user_id)
    return HttpResponse(status=204)


def _prefs_payload(user_id: int) -> dict:
    prefs = center.prefs_of(user_id)
    return {"bell": prefs.bell, "email": prefs.email, "telegram": prefs.telegram,
            "telegram_linked": telegram.is_linked(user_id)}


@api_view(methods=("GET",))
def _prefs_get(request):
    return _prefs_payload(request.token.user_id)


@api_view(methods=("PATCH",), body=schemas.PrefsPatch)
def _prefs_patch(request, data: schemas.PrefsPatch):
    user_id = request.token.user_id
    prefs = center.prefs_of(user_id)
    for key, value in data.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(prefs, key, value)
    # Колокольчик выключить нельзя: события задач, календаря, мессенджера,
    # конференций и кадров пишутся с deliver=False и приходят ТОЛЬКО в него —
    # «только e-mail» тихо отрезал бы их все. Отсюда и «хотя бы один канал».
    if not prefs.bell:
        raise DomainError(
            "E-NTF-01",
            "Колокольчик выключить нельзя: события задач, календаря и мессенджера "
            "приходят только в него.",
            fields=[{"field": "bell", "message": "колокольчик обязателен"}])
    # Telegram без привязанного чата — канал, который ничего не доставит.
    if prefs.telegram and not telegram.is_linked(user_id):
        raise DomainError(
            "E-NTF-02", "Сначала подключите Telegram: нажмите «Подключить Telegram».",
            fields=[{"field": "telegram", "message": "чат не привязан"}])
    prefs.save()
    return _prefs_payload(user_id)


def prefs(request):
    if request.method == "GET":
        return _prefs_get(request)
    if request.method == "PATCH":
        return _prefs_patch(request)
    return json_error("Method Not Allowed", 405)


@api_view(methods=("POST",))
def telegram_link(request):
    return {"url": telegram.start_link(request.token.user_id)}


@api_view(methods=("POST",), auth=None)
def telegram_webhook(request):
    if not telegram.secret_ok(request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")):
        return json_error("Forbidden", 403)
    try:
        update = json.loads(request.body or b"{}")
    except ValueError:
        return json_error("Bad Request", 400)
    if isinstance(update, dict):
        telegram.complete_link(update)
    return {"ok": True}
