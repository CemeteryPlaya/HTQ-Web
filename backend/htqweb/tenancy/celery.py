"""Компания в задачах Celery.

У задачи нет HTTP-запроса, поэтому CompanyContextMiddleware до неё не
достаёт, а contextvar в воркере пуст. Компания передаётся ЯВНЫМ аргументом
``company_slug`` — и её отсутствие является ошибкой, а не поводом взять
public.

Почему именно так: молчаливый откат на public означал бы, что задача
отработала «успешно», не найдя ни одной строки в пустой схеме. Такой дефект
не даёт ни ошибки, ни записи в лог, и обнаруживается через недели по
отсутствию результата. Это ровно тот класс подмен, ради которого на
платформе введён FALLBACK_MODE=strict.

Порядок декораторов при использовании:

    @shared_task
    @company_task
    def rebuild_something(company_slug: str, item_id: int):
        ...

company_task идёт БЛИЖЕ к функции, чтобы Celery сериализовал уже обёрнутый
вызов вместе с company_slug.
"""

from __future__ import annotations

from functools import wraps

from .db import use_company


class MissingCompanyArgument(RuntimeError):
    """Задача с @company_task вызвана без company_slug."""


def company_task(fn):
    """Развернуть kwarg ``company_slug`` в контекст компании на время задачи."""

    @wraps(fn)
    def wrapper(*args, **kwargs):
        slug = kwargs.pop("company_slug", None)
        if not slug:
            raise MissingCompanyArgument(
                f"{fn.__module__}.{fn.__qualname__} требует company_slug. "
                "Задача, работающая с данными компании, обязана получать её "
                "явно: контекста запроса в воркере нет."
            )
        with use_company(slug):
            return fn(*args, **kwargs)

    return wrapper
