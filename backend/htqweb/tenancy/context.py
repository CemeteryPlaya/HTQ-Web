"""Текущая компания запроса и вычисление имени её схемы.

Хранение — contextvars, а не threading.local, намеренно: под ASGI
(backend-asgi обслуживает SSE и WebSocket) в одном потоке живёт много
корутин, и thread-local утёк бы между ними. ContextVar копируется в каждую
задачу asyncio, поэтому изоляция сохраняется и там.

Значение — slug, а не объект Company: контекст обязан быть дешёвым и
сериализуемым (он же уходит аргументом в задачи Celery, см.
htqweb/tenancy/celery.py). Резолв slug -> строка реестра делает
apps.companies.interface с собственным кэшем.
"""

from __future__ import annotations

import contextvars

# Префикс схемы компании. Отдельный префикс, а не голый slug, чтобы схемы
# компаний нельзя было спутать с public/holding/служебными схемами Postgres
# при ручном разборе в psql.
SCHEMA_PREFIX = "co_"

# Схема со сводными UNION ALL-представлениями поверх всех активных компаний.
HOLDING_SCHEMA = "holding"


class NoCompanyContext(RuntimeError):
    """Обращение к компании там, где контекст не установлен."""


_current: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "htq_company_slug", default=None,
)


def schema_for(slug: str) -> str:
    """Имя схемы Postgres для компании.

    Дефис допустим в DNS-метке (slug — поддомен), но в неэкранированном
    идентификаторе Postgres он бы разобрался как минус, поэтому заменяется.
    """
    return SCHEMA_PREFIX + slug.replace("-", "_")


def current_company() -> str:
    slug = _current.get()
    if slug is None:
        raise NoCompanyContext(
            "Контекст компании не установлен. В HTTP-запросе его ставит "
            "CompanyContextMiddleware, в задаче Celery — декоратор "
            "@company_task, в тесте — фикстура company_context."
        )
    return slug


def current_company_or_none() -> str | None:
    return _current.get()


def set_company(slug: str | None) -> contextvars.Token:
    return _current.set(slug)


def reset_company(token: contextvars.Token) -> None:
    _current.reset(token)
