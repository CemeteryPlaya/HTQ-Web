"""Кто имеет право видеть встречу, её запись и протокол.

Одна функция на всю аппку — её зовут все публичные вьюхи. Правило (решение
заказчика): **участники встречи + администраторы платформы**.

Гости по ссылке не проходят здесь вообще, и не потому, что мы их отсеиваем:
гостевой JWT имеет ``token_type="guest"``, а ``htqweb.http._authenticate_jwt``
принимает только ``access``. То есть до этой функции гость просто не
доберётся — его отобьёт 401 на уровне ``api_view``. Это вторая линия обороны
из htqweb/authn/jwt.py::issue_guest_token, и дублировать её здесь незачем.
"""

from __future__ import annotations

import datetime

from django.db.models import Q
from django.http import Http404

from apps.conference.models import ConferenceParticipant, ConferenceSession
from apps.core.services import ServiceDisabled
from htqweb.fallback import fallback


def my_conference_event_ids(request) -> set[int]:
    """Календарные события конференций, куда позвали автора запроса.

    Мемоизация на объекте ``request``, а не в глобальном кэше: права не
    должны переживать запрос, иначе снятое приглашение продолжало бы
    действовать.

    ``period_start``/``period_end`` намеренно широкие: видимость истории не
    ограничена сегодняшним днём — человек вправе увидеть встречу, на которую
    его звали в прошлом месяце. Это МОМЕНТЫ, не даты — как и у
    ``list_user_conference_events`` (см. её докстринг): интервал берётся с
    огромным запасом, а не «весь диапазон дат», поэтому вопрос часового
    пояса здесь не встаёт вовсе.
    """
    cached = getattr(request, "_conference_event_ids", None)
    if cached is not None:
        return cached

    token = getattr(request, "token", None)
    result: set[int] = set()
    if token is not None and token.user_id:
        try:
            from apps.tasks.interface import list_user_conference_events

            far_past = datetime.datetime(2000, 1, 1, tzinfo=datetime.timezone.utc)
            far_future = datetime.datetime(2100, 1, 1, tzinfo=datetime.timezone.utc)
            result = {row["id"] for row in list_user_conference_events(
                token.user_id, period_start=far_past, period_end=far_future)}
        except ServiceDisabled as exc:
            # Предусмотренная деградация: сосед выключен в реестре. Встреча
            # просто исчезает из списка по третьему основанию, человек
            # видит её по-прежнему по факту участия. expected=True — strict
            # режим разработчика её не роняет.
            fallback("conference.access.calendar_unavailable", None,
                     reason="календарь недоступен — видимость только по факту участия",
                     expected=True, exc=exc)
        except Exception as exc:
            # НЕ предусмотренная деградация: сосед включён, но упал по своей
            # причине (баг, сломанный запрос). Отдельный site — чтобы не
            # смешивать с expected=True в метрике — и expected=False: под
            # pytest (strict) это осознанно бросит FallbackNotAllowed, чтобы
            # настоящая поломка была громкой, а не тихо растворилась в
            # INFO-логе, на который алерт не смотрит.
            fallback("conference.access.calendar_failed", None,
                     reason="сбой при обращении к календарю — не выключенный сосед, а ошибка",
                     expected=False, exc=exc)

    request._conference_event_ids = result
    return result


def may_view(session: ConferenceSession, request) -> bool:
    """Может ли автор запроса смотреть эту встречу."""
    token = getattr(request, "token", None)
    if token is None:
        return False
    if token.is_elevated:
        return True
    if session.created_by_id is not None and session.created_by_id == token.user_id:
        return True
    if session.participants.filter(user_id=token.user_id).exists():
        return True
    if (session.calendar_event_id is not None
            and session.calendar_event_id in my_conference_event_ids(request)):
        return True
    return False


def get_visible_session(session_id: int, request) -> ConferenceSession:
    """Встреча по id или 404 — включая случай «есть, но не для вас».

    Отказ в доступе намеренно выглядит как «не найдено», а не как 403:
    иначе перебором id можно было бы выяснить, что двадцатого числа встреча
    была, кто её собирал и как она называлась, — а это ровно те сведения,
    которые мы и закрываем.
    """
    session = (ConferenceSession.objects
               .filter(pk=session_id)
               .prefetch_related("participants")
               .first())
    if session is None or not may_view(session, request):
        raise Http404("Конференция не найдена")
    return session


def visible_sessions(request):
    """Базовый queryset истории для текущего пользователя."""
    token = getattr(request, "token", None)
    queryset = ConferenceSession.objects.all()
    if token is not None and token.is_elevated:
        return queryset
    if token is None:
        return queryset.none()
    # Видимость через ПОДЗАПРОС по id, а не через filter(participants__...).
    #
    # Разница не косметическая. Фильтр по связи создаёт JOIN, и Django
    # переиспользует его в последующем annotate(Count("participants")) —
    # то есть счётчик участников в списке считал бы только строки,
    # прошедшие фильтр, и у рядового сотрудника на каждой встрече стояло
    # бы «1 участник». Подзапрос джойна не создаёт: и права те же, и
    # число честное. Заодно отпадает distinct().
    attended = (ConferenceParticipant.objects
                .filter(user_id=token.user_id)
                .values("session_id"))
    invited_to = my_conference_event_ids(request)
    return queryset.filter(
        # Автор встречи виден себе, даже если журнал участников не доехал
        # (SFU упал между стартом сессии и первым participants-событием).
        Q(created_by_id=token.user_id)
        | Q(pk__in=attended)
        | Q(calendar_event_id__in=invited_to),
    )
