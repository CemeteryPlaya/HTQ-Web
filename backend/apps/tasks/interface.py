"""Публичный API аппки tasks для ДРУГИХ аппок (контракт PLAN.md §7).

Производитель: Поток B. Прямой импорт ``apps.tasks.models`` /
``apps.tasks.services`` из другой аппки запрещён и ловится
``apps/core/tests/test_app_isolation.py`` — только через этот модуль.

Каждая функция начинается с ``require_service("tasks")``: если аппка
выключена, вызывающий получает ``ServiceDisabled``, который ``api_view``
превращает в 503-конверт, а не в молчаливый неверный ответ. Возвращаются
простые словари, никогда ORM-объекты.

``push_notification`` — то, чем в FastAPI был подписчик
``workers/notify_sync.py``: messenger и email публиковали событие в Redis, а
task-service материализовал его в строку ``Notification``. В монолите шина не
нужна — сосед вызывает эту функцию напрямую, в своей же транзакции. Окно
дедупликации подписчика сохранено (см. докстринг функции), иначе повторная
доставка события породила бы дубли в колокольчике.

Сигнатуры ``get_task_brief``/``get_tasks_brief`` §7 помечал как «по
необходимости» — они реализованы, потому что стоят один запрос, а не потому
что кто-то уже зовёт; ``push_notification`` — реальная потребность Потока A
(messenger, mail), и её форму нужно согласовать при интеграции.
"""
from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from apps.core.services import require_service

_BRIEF_FIELDS = ("id", "key", "summary", "status", "assignee_id",
                 "department_id")

# Окно, в котором повторное событие с тем же (получатель, цель, актор, verb)
# считается дублем и не создаёт вторую строку. Перенесено из
# services/task/app/workers/notify_sync.py — там оно защищало от повторной
# доставки Redis-сообщения, здесь защищает от повторного вызова соседом
# (ретрай его Celery-задачи, двойной сабмит формы).
_DEDUPE_WINDOW = timedelta(minutes=5)


def get_task_brief(task_id: int) -> dict | None:
    """Минимальная карточка задачи, либо ``None``, если id не резолвится.

    Форма ``{id, key, summary, status, assignee_id, department_id}`` —
    достаточно, чтобы сосед показал задачу в своём списке, и ничего лишнего:
    описание, участники и вложения остаются приватными для домена.
    Мягко удалённые задачи не резолвятся — для соседа их не существует.
    """
    require_service("tasks")
    from .models import Task

    row = (Task.objects.filter(pk=task_id, is_deleted=False)
           .values(*_BRIEF_FIELDS).first())
    return dict(row) if row is not None else None


def get_tasks_brief(task_ids: list[int]) -> list[dict]:
    """Пакетный вариант ``get_task_brief`` — один запрос на все id.

    Неизвестные id просто отсутствуют в результате (тот же контракт
    «unknown -> omitted», что у ``apps.users.interface.get_users_brief``).
    """
    require_service("tasks")
    from .models import Task

    return [dict(row) for row in
            Task.objects.filter(pk__in=list(task_ids), is_deleted=False)
            .values(*_BRIEF_FIELDS)]


def push_notification(*, recipient_id: int, verb: str,
                      actor_id: int | None = None,
                      actor_avatar_url: str | None = None,
                      target_type: str | None = None,
                      target_id: int | None = None) -> dict | None:
    """Создать уведомление в колокольчике от имени соседней аппки.

    Замена подписчику ``notify_sync``: messenger («вам написали») и mail
    («новое письмо») зовут это вместо публикации в Redis.

    Идемпотентно в пределах ``_DEDUPE_WINDOW``: если такое же уведомление
    этому получателю уже создано за последние 5 минут — возвращается
    ``None`` и новая строка НЕ пишется.

    ``actor_avatar_url`` сохраняется снимком на момент записи: это
    точка-во-времени, и последующая смена аватара не должна переписывать
    историю (см. ``apps.tasks.models.Notification``).
    """
    require_service("tasks")
    from .models import Notification

    since = timezone.now() - _DEDUPE_WINDOW
    if Notification.objects.filter(
            recipient_id=recipient_id, actor_id=actor_id, verb=verb,
            target_type=target_type, target_id=target_id,
            created_at__gte=since).exists():
        return None

    row = Notification.objects.create(
        recipient_id=recipient_id, actor_id=actor_id, verb=verb,
        actor_avatar_url=actor_avatar_url, target_type=target_type,
        target_id=target_id,
    )
    return {"id": row.id, "recipient_id": row.recipient_id, "verb": row.verb,
            "target_type": row.target_type, "target_id": row.target_id,
            "created_at": row.created_at}


def _conference_payload(event, invitee_ids: list[int]) -> dict:
    return {
        "id": event.id,
        "title": event.title,
        "start_at": event.start_at,
        "end_at": event.end_at,
        "creator_id": event.creator_id,
        "room_id": event.conference_room_id,
        "invitee_ids": invitee_ids,
    }


def get_conference_event_for_room(room_id: str) -> dict | None:
    """Событие календаря, которому принадлежит эта комната.

    Поиск ТОЧНЫЙ, без разрешения неоднозначностей: комната уникальна среди
    conference-событий (constraint ``uq_calendar_conference_room``). ``None``
    — встречу собрали кнопкой «Создать комнату», минуя календарь; это
    нормальный случай, а не ошибка.
    """
    require_service("tasks")
    from .models import CalendarEvent

    event = (CalendarEvent.objects
             .filter(event_type="conference",
                     conference_room_id=(room_id or "").strip())
             .prefetch_related("participants")
             .first())
    if event is None:
        return None

    invitees = {p.user_id for p in event.participants.all()}
    if event.creator_id:
        invitees.add(event.creator_id)
    return _conference_payload(event, sorted(invitees))


def list_user_conference_events(user_id: int | None, *, period_start, period_end,
                                include_all: bool = False) -> list[dict]:
    """Конференции периода ``[period_start, period_end)``, где человек участник
    или автор.

    ``period_start``/``period_end`` — это МОМЕНТЫ (aware ``datetime``), не
    даты. Раньше здесь стояли даты и фильтр по ``start_at__date``/
    ``end_at__date``, а ``__date`` Django вычисляет в АКТИВНОМ поясе — а
    активного пояса в проекте нет (``timezone.activate()`` нигде не
    вызывается), значит бралась дата в UTC. Вызывающие снаружи (обзор
    конференций) считают границы суток в поясе платформы, и «дата события в
    UTC» с «датой суток в Алматы» — разные числа в районе полуночи;
    событие тихо выпадало из окна. Сравнение по моментам это убирает вовсе:
    вопрос «в каком поясе брать дату» здесь просто не возникает — интервалы
    либо пересекаются, либо нет, независимо от пояса. Пояс нужен ровно один
    раз — там, где сутки превращаются в границы (см.
    ``apps.conference.services.platform_time``), а не здесь.

    ``include_all=True`` — для администратора платформы: фильтр по человеку
    снимается целиком.

    Отменённые экземпляры (``EventException``) выбрасываются: их участники не
    должны ни видеть встречу в списке, ни получать письмо о её начале.
    Механизма повторов у событий сейчас нет, поэтому «экземпляр» — это само
    событие, отменённое на свою же дату.
    """
    require_service("tasks")
    from django.db.models import Q

    from .models import CalendarEvent

    # Пересечение интервалов: событие входит в период, если начинается ДО
    # его конца и заканчивается ПОСЛЕ его начала (конец периода —
    # эксклюзивная граница).
    queryset = (CalendarEvent.objects
                .filter(event_type="conference",
                        conference_room_id__isnull=False,
                        start_at__lt=period_end,
                        end_at__gt=period_start)
                .exclude(exceptions__is_cancelled=True)
                .prefetch_related("participants"))
    if not include_all:
        if user_id is None:
            return []
        queryset = queryset.filter(
            Q(creator_id=user_id) | Q(participants__user_id=user_id))

    rows = []
    for event in queryset.distinct().order_by("start_at"):
        invitees = {p.user_id for p in event.participants.all()}
        if event.creator_id:
            invitees.add(event.creator_id)
        rows.append(_conference_payload(event, sorted(invitees)))
    return rows
