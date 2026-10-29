"""Цепочка исполнения автоматизации (K-37, решение пользователя 26.10).

Цепочка — всё, что автоматизация делает в ответ на одно действие человека,
нажатие кнопки или запуск команды: события обрабатываются очередью, правка,
сделанная правилом, — тоже событие (как в Trello). Пределы: глубина до
``MAX_DEPTH``, одно правило выполняется на задаче один раз за цепочку, не
больше ``MAX_ACTIONS`` действий. Состояние — ``contextvar``: цепочка живёт в
одном потоке на время запроса или задачи Celery и не переживает их.

Пока исполняется правило (``running``), сервисы задач видят, что действует
автоматизация: журнал задачи пишет ``via_rule_id``, запрет ручного переноса
не проверяется, а события правки копятся в ``produced`` и попадают в очередь
только после того, как правило выполнилось целиком (у откатившегося правила
они отбрасываются).

У цепочки есть зачинщик (``initiator``) — человек, чьё действие её запустило,
или нажавший кнопку; у команд по сроку и расписанию его нет. Уведомления о
правках автоматизации ему не приходят: результат у него на экране.
"""

from __future__ import annotations

from collections import deque
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import date, datetime
from zoneinfo import ZoneInfo

from django.conf import settings
from django.utils import timezone

MAX_DEPTH = 5
MAX_ACTIONS = 50
#: Новых задач за цепочку: правило «создана → создать задачу» иначе плодило бы
#: задачи до предела глубины (спецификация логики §4).
MAX_CREATED = 10


def local_tz() -> ZoneInfo:
    """Пояс людей платформы (``PLATFORM_TIME_ZONE``, Алматы): сроки и время
    расписаний автоматизации. ``TIME_ZONE`` хранения — UTC, и «сегодня» по UTC
    до пяти утра — ещё вчера."""
    return ZoneInfo(settings.PLATFORM_TIME_ZONE)


def now_local() -> datetime:
    return timezone.now().astimezone(local_tz())


def today() -> date:
    return now_local().date()


@dataclass
class Event:
    """Событие задачи. ``actor_id`` — кто сделал (у правила — ``None``),
    ``by_automation`` — сделала автоматизация (у кнопки актор — нажавший)."""

    type: str
    task_id: int
    actor_id: int | None
    data: dict = field(default_factory=dict)
    depth: int = 0
    by_automation: bool = False


@dataclass
class Running:
    """Исполняемая автоматизация: от чьего имени пишется журнал задачи и
    уведомления (у правила — «Автоматизация», ``None``; у кнопки — нажавший)
    и кто сделал событие, на которое она сработала."""

    rule_id: int
    actor_id: int | None
    event_actor_id: int | None
    depth: int
    produced: list = field(default_factory=list)


@dataclass
class Chain:
    queue: deque = field(default_factory=deque)
    actions: int = 0
    executed: set = field(default_factory=set)
    running: Running | None = None
    rules_cache: dict = field(default_factory=dict)
    initiator_id: int | None = None
    #: (правило, задача), у которых «условия не сошлись» уже в журнале.
    no_match: set = field(default_factory=set)
    created: int = 0
    #: Ошибка последнего запуска — её показывает нажавший кнопку.
    last_error: str | None = None


class ChainLimit(Exception):
    """Цепочка упёрлась в предел посреди действий правила (новых задач больше
    ``MAX_CREATED``): правило откатывается, в журнале — «упёрлось в предел»."""


_chain: ContextVar[Chain | None] = ContextVar("tasks_automation_chain", default=None)


def current() -> Chain | None:
    return _chain.get()


def running() -> Running | None:
    chain = _chain.get()
    return chain.running if chain is not None else None


def in_automation() -> bool:
    """Правку делает автоматизация — запрет ручного переноса не проверяется."""
    return running() is not None


def current_rule_id() -> int | None:
    """Для журнала задачи: правку сделала эта автоматизация (``via_rule_id``)."""
    now = running()
    return now.rule_id if now is not None else None


def current_actor(default: int | None) -> int | None:
    """Кто действует: внутри автоматизации — её актор, иначе ``default``."""
    now = running()
    return now.actor_id if now is not None else default


def initiator() -> int | None:
    """Зачинщик цепочки, пока исполняется автоматизация: его не уведомлять."""
    chain_ = _chain.get()
    if chain_ is None or chain_.running is None:
        return None
    return chain_.initiator_id


@contextmanager
def chain(initiator_id: int | None = None):
    """Новая цепочка или уже идущая (вложенный вызов её переиспользует).
    ``initiator_id`` — зачинщик новой цепочки."""
    existing = _chain.get()
    if existing is not None:
        yield existing, False
        return
    fresh = Chain(initiator_id=initiator_id)
    token = _chain.set(fresh)
    try:
        yield fresh, True
    finally:
        _chain.reset(token)


@contextmanager
def run_as(chain_: Chain, rule_id: int, *, actor_id: int | None,
           event_actor_id: int | None, depth: int):
    """Исполнение одной автоматизации: события её правок — в ``produced``."""
    previous = chain_.running
    chain_.running = Running(rule_id=rule_id, actor_id=actor_id,
                             event_actor_id=event_actor_id, depth=depth)
    try:
        yield chain_.running
    finally:
        chain_.running = previous
