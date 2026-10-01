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

from apps.core.services import require_service

_BRIEF_FIELDS = ("id", "key", "summary", "status", "assignee_id",
                 "department_id")

# Паспорт проекта для соседа. ``color`` и ``status`` здесь не украшение:
# договорная карточка рисует проект бейджем, и без них ей пришлось бы либо
# заводить свою палитру (и разъехаться с доской задач), либо ходить за ней
# вторым запросом в чужой HTTP-эндпоинт.
_PROJECT_BRIEF_FIELDS = ("id", "name", "status", "color",
                         "start_date", "end_date")

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


def get_project_brief(project_id: int) -> dict | None:
    """Паспорт проекта, либо ``None``, если id не резолвится.

    Нужен домену договоров: бюджет заводится «на проект», и до появления
    связи проект жил там отдельной строкой ``Administrator.project_name`` —
    то есть одно и то же название существовало в двух местах и расходилось
    при первой же переименовке.

    Отдаёт ``{id, name, status, color, start_date, end_date}`` — ровно то,
    чем проект ПОДПИСЫВАЮТ. Состав объектов, блоки, задачи и участники
    остаются приватными для домена: соседу нужна ссылка, а не содержимое.
    """
    require_service("tasks")
    from .models import Project

    row = (Project.objects.filter(pk=project_id)
           .values(*_PROJECT_BRIEF_FIELDS).first())
    return dict(row) if row is not None else None


def get_projects_brief(project_ids: list[int]) -> list[dict]:
    """Пакетный вариант ``get_project_brief`` — один запрос на все id.

    Существует ровно ради списков: у договоров есть страница со всеми
    бюджетами, и поштучный ``get_project_brief`` превратил бы её в N+1.
    Неизвестные id просто отсутствуют в результате (тот же контракт
    «unknown -> omitted», что у ``get_tasks_brief``).
    """
    require_service("tasks")
    from .models import Project

    return [dict(row) for row in
            Project.objects.filter(pk__in=list(project_ids))
            .values(*_PROJECT_BRIEF_FIELDS)]


def find_project_by_name(name: str) -> dict | None:
    """Проект по ТОЧНОМУ названию, либо ``None``.

    ``Project.name`` уникален, поэтому поиск однозначен. Функция нужна для
    сшивания уже существующих данных: в договорах проект годами хранился
    строкой, и связать старые записи можно только по названию. Для нового
    ввода она не нужна — там выбирают из списка и присылают id.

    Регистр и краевые пробелы не игнорируются намеренно: «похоже совпало» —
    худший исход для связи, которая потом определяет бюджет проекта.
    """
    require_service("tasks")
    from .models import Project

    row = (Project.objects.filter(name=name)
           .values(*_PROJECT_BRIEF_FIELDS).first())
    return dict(row) if row is not None else None


def projects_without_ref() -> list[dict]:
    """Доски без ссылки на «Проект» БЗО — для ``project_link_tasks``.

    Поля доски — в словаре «Проекта» (``name``, ``status`` — ``active`` /
    ``closed`` / ``archived``, ``date_start``, ``date_end``,
    ``manager_user_id`` — владелец доски): команда заводит «Проект» из них,
    и доска после связи повторяет его без правок. Своего кода у доски нет —
    код «Проекта» команда выводит из ``id``.
    """
    require_service("tasks")
    from .models import Project
    from .services.project_link import STATUS_TO_PROJECT

    return [{"id": row["id"], "name": row["name"], "status": STATUS_TO_PROJECT[row["status"]],
             "date_start": row["start_date"], "date_end": row["end_date"],
             "manager_user_id": row["owner_id"]}
            for row in Project.objects.filter(project_ref="").order_by("id")
            .values("id", "name", "status", "start_date", "end_date", "owner_id")]


def linked_project_refs() -> set[str]:
    """Ключи «Проектов», у которых уже есть доска задач (одна на проект)."""
    require_service("tasks")
    from .models import Project

    return set(Project.objects.exclude(project_ref="").values_list("project_ref", flat=True))


def set_project_ref(project_id: int, project_ref: str) -> None:
    """Записать ссылку доски на «Проект» БЗО (строка UUID, не FK). Поля доски
    вызывающий уже перенёс в «Проект» (``projects_without_ref``)."""
    require_service("tasks")
    from .models import Project

    Project.objects.filter(pk=project_id).update(project_ref=project_ref)


class ContractorLinkConflict(Exception):
    """Связать партнёра с контрагентом нельзя: партнёр уже за другим
    контрагентом, БИН/ИИН пары расходится и т. п. Текст — для человека,
    вызывающий отдаёт его как 409.

    Своё исключение интерфейса, а не сервисное: соседу нельзя импортировать
    ``apps.tasks.services``, а ловить ему что-то нужно."""


def _bpp_counterparties_of(source_ids) -> dict[str, str]:
    """``{ключ контрагента contracts строкой: ключ контрагента bpp}`` — по
    связям переноса B6.1. Неперенесённых в ответе нет."""
    from apps.bpp import interface as bpp

    from .services.contractor_service import MIGRATED_COUNTERPARTY

    source_type, target_type = MIGRATED_COUNTERPARTY
    out = {}
    for source, targets in bpp.migrated_targets(source_type, source_ids).items():
        for target in targets:
            if target["target_type"] == target_type:
                out[source] = target["target_id"]
    return out


def get_contractors_by_counterparty(source_ids) -> dict[int, dict]:
    """Партнёры, связанные с контрагентами «Договоров», — ``{ключ
    контрагента contracts: {id, name, status}}``. Для карточки контрагента в
    «Договорах»: «работает у нас на объектах как партнёр …». Батчем — реестр
    контрагентов показывает всех разом. Контрагенты без партнёра в ответ не
    попадают.

    С A6.1 партнёр ссылается на контрагента ``bpp``, поэтому контрагент
    «Договоров» находит своего партнёра через связь переноса B6.1: не
    перенесён — партнёра у него нет. Модуль ``bpp`` выключен —
    ``ServiceDisabled`` (сосед его уже ловит)."""
    require_service("tasks")
    from .services import contractor_service

    ids = sorted({int(source) for source in source_ids if source is not None})
    if not ids:
        return {}
    moved = _bpp_counterparties_of(ids)
    partners = contractor_service.contractors_by_counterparty(moved.values())
    out = {}
    for source, key in moved.items():
        row = partners.get(key)
        if row is not None:
            out[int(source)] = {"id": row.id, "name": row.name, "status": str(row.status)}
    return out


def link_contractor_to_counterparty(contractor_id: int, source_id: int) -> dict:
    """Связать партнёра с контрагентом «Договоров» — для карточки
    контрагента, заведённой «из партнёра». Зовётся в транзакции соседа:
    откатится создание контрагента — откатится и связь.

    С A6.1 партнёр связывается с контрагентом ``bpp``, в который перенесён
    контрагент «Договоров» (связь переноса B6.1). Неперенесённый — отказ
    ``ContractorLinkConflict``: связывать партнёра теперь нужно на его
    карточке, выбором контрагента «Закупок и оплат». Дальше — те же
    проверки, что у правки карточки партнёра (БИН/ИИН пары, один партнёр на
    контрагента), плюс запрет молча перепривязать уже связанного партнёра.
    Неизвестный партнёр — ``Http404``.
    """
    require_service("tasks")
    from .services import contractor_service

    target = _bpp_counterparties_of([source_id]).get(str(source_id))
    if target is None:
        raise ContractorLinkConflict(
            "Контрагент не перенесён в модуль «Закупки и оплаты» — свяжите партнёра "
            "с контрагентом на карточке партнёра")
    try:
        row = contractor_service.link_counterparty(contractor_id, target)
    except contractor_service.CounterpartyLinkConflict as exc:
        raise ContractorLinkConflict(str(exc)) from exc
    return {"id": row.id, "name": row.name, "status": str(row.status)}


def unlink_counterparty(source_id: int) -> None:
    """Контрагента «Договоров» удалили. С A6.1 партнёр ссылается на
    контрагента ``bpp``, а не «Договоров», поэтому снимать нечего: удаление
    старой карточки контрагента ``bpp`` не трогает. Функция остаётся ради
    вызова из ``apps.contracts`` (раздел заморожен, A6.2) — идемпотентно и
    без действия."""
    require_service("tasks")
    del source_id


def push_notification(*, recipient_id: int, verb: str,
                      actor_id: int | None = None,
                      actor_avatar_url: str | None = None,
                      target_type: str | None = None,
                      target_id: int | str | None = None) -> dict | None:
    """Создать уведомление в колокольчике от имени соседней аппки.

    Замена подписчику ``notify_sync``: messenger («вам написали»), mail
    («новое письмо»), конференции и кадры зовут это вместо публикации в Redis.

    С задачи A1.5 модуля БЗО строка пишется в центр уведомлений
    (``apps.notifications``, public), а не в ``tasks.Notification``: сигнатура
    и окно дедупликации прежние, компания — из текущего контекста (без
    контекста уведомление общее). Только колокольчик (``deliver=False``):
    письмо о каждом сообщении было бы новым поведением, а не переездом.

    Идемпотентно в пределах ``_DEDUPE_WINDOW``: если такое же уведомление
    этому получателю уже создано за последние 5 минут — возвращается
    ``None`` и новая строка НЕ пишется.

    ``actor_avatar_url`` сохраняется снимком на момент записи: это
    точка-во-времени, и последующая смена аватара не должна переписывать
    историю.
    """
    require_service("tasks")
    from apps.notifications import interface as notifications
    from htqweb.tenancy.context import current_company_or_none

    ids = notifications.notify(
        recipients=[recipient_id], event=f"tasks.{target_type or 'generic'}", title=verb,
        company_slug=current_company_or_none(), target_type=target_type or "",
        target_id=str(target_id) if target_id is not None else "", actor_id=actor_id,
        actor_avatar_url=actor_avatar_url, deliver=False,
        dedupe_window_seconds=int(_DEDUPE_WINDOW.total_seconds()))
    if not ids:
        return None
    return {"id": ids[0], "recipient_id": recipient_id, "verb": verb,
            "target_type": target_type, "target_id": target_id}


def legacy_notifications() -> list[dict]:
    """Все строки старой ленты ``tasks.Notification`` текущей компании — для
    переноса в центр уведомлений (``manage.py notifications_import_tasks``).

    Ключи: ``id, recipient_id, actor_id, verb, actor_avatar_url, target_type,
    target_id, task_id, is_read, read_at, created_at``. После переноса на бою
    модель удаляется отдельной contract-миграцией.
    """
    require_service("tasks")
    from .models import Notification

    return list(Notification.objects.order_by("id").values(
        "id", "recipient_id", "actor_id", "verb", "actor_avatar_url", "target_type",
        "target_id", "task_id", "is_read", "read_at", "created_at"))


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
