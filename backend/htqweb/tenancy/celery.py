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
    def rebuild_something(item_id: int):
        ...

    rebuild_something.delay(company_slug="htq-kz", item_id=1)

company_task идёт БЛИЖЕ к функции, чтобы Celery сериализовал уже обёрнутый
вызов вместе с company_slug.

ВАЖНО: ``company_slug`` обязан передаваться ИМЕНОВАННЫМ аргументом
(``company_slug="..."``), а не позиционным. Декоратор смотрит только в
``kwargs`` — попытка позиционного разбора потребовала бы знать сигнатуру
обёрнутой функции и сломалась бы на задачах с ``*args``.

``company_slug`` в саму обёрнутую функцию НЕ передаётся — декоратор
вынимает его из ``kwargs`` (``kwargs.pop``), поэтому ``rebuild_something``
не объявляет параметр ``company_slug`` в своей сигнатуре. Если телу задачи
нужно знать текущий slug (например, для лога), внутри блока
``with use_company(slug)`` он уже установлен в контекст — читайте его через
``htqweb.tenancy.context.current_company()``, а не заводите второй, теневой
канал передачи одного и того же значения.

## Шаблон «диспетчер + веер»

Задача tenant-аппки (``settings.TENANT_APPS``) обязана быть либо
``@company_task``, либо явно помечена диспетчером через
``@company_dispatch_task`` — это проверяет рефлективный мета-тест
``apps/core/tests/test_invariants.py::
test_tenant_app_tasks_use_company_task_or_are_marked_dispatchers``. У
диспетчера своей компании нет: beat планирует его без аргументов, он читает
``active_company_slugs()`` (``apps.companies.interface``) и веером ставит по
одной ``@company_task``-задаче на каждую действующую компанию —
``fan_out_to_companies`` делает это за диспетчера:

    @shared_task
    @company_dispatch_task
    def rebuild_something_dispatch():
        require_service("<domain>")
        return fan_out_to_companies(rebuild_something, label="rebuild_something_dispatch")

Сбой постановки одной компании не должен обрывать веер по остальным —
``fan_out_to_companies`` ловит исключение на каждой компании отдельно,
логирует его и идёт дальше.
"""

from __future__ import annotations

import logging
from functools import wraps

from .db import use_company

logger = logging.getLogger(__name__)


class MissingCompanyArgument(RuntimeError):
    """Задача с @company_task вызвана без company_slug."""


def company_task(fn):
    """Развернуть kwarg ``company_slug`` в контекст компании на время задачи.

    ``company_slug`` обязан передаваться ИМЕНОВАННЫМ аргументом. Декоратор
    читает только ``kwargs``, потому что попытка позиционного разбора потребовала
    бы инспектировать сигнатуру обёрнутой функции и сломалась бы на задачах
    с ``*args``.
    """

    @wraps(fn)
    def wrapper(*args, **kwargs):
        slug = kwargs.pop("company_slug", None)
        if not slug:
            raise MissingCompanyArgument(
                f"{fn.__module__}.{fn.__qualname__} требует company_slug. "
                "Задача, работающая с данными компании, обязана получать её "
                "явно: контекста запроса в воркере нет. "
                "Если аргумент передан — проверьте, что он ИМЕНОВАННЫЙ, а не позиционный: "
                "декоратор читает только kwargs."
            )
        with use_company(slug):
            return fn(*args, **kwargs)

    # Явный маркер для мета-теста (apps/core/tests/test_invariants.py):
    # "задача tenant-аппки задекорирована @company_task?" — по имени функции
    # или по эвристике не отличить, а маркер атрибутом не зависит от
    # inspect.unwrap и не путается с company_dispatch_task ниже.
    wrapper.is_company_task = True
    return wrapper


def company_dispatch_task(fn):
    """Пометить задачу-диспетчера: она компанией не оперирует.

    В отличие от ``company_task`` — НЕ оборачивает функцию (диспетчеру
    нечего разворачивать в контекст, он его никогда не получает) и НЕ
    требует ``company_slug`` при вызове. Единственная роль — явный сигнал
    мета-тесту, что задача tenant-аппки намеренно свободна от
    ``@company_task``: она только читает реестр компаний
    (``apps.companies.interface``, не тенантный) и веером ставит реальные
    задачи через ``fan_out_to_companies``.

    Без этого маркера мета-тест не смог бы отличить диспетчера от
    забытого ``@company_task`` иначе, чем по имени функции — а соглашение
    об имени однажды разойдётся с кодом молча.
    """
    fn.is_company_dispatch_task = True
    return fn


def fan_out_to_companies(task, *, label: str) -> dict:
    """Поставить ``task.delay(company_slug=...)`` по каждой действующей компании.

    Общее тело шаблона «диспетчер + веер» (см. докстринг модуля) — вызывается
    из тела задачи, помеченной ``@company_dispatch_task``. Компании берутся
    из ``active_company_slugs()`` (не всех, только действующих — архивная
    компания сама выпадает из веера, без правок вызывающего кода).

    Сбой ПОСТАНОВКИ задачи для одной компании (например, недоступный брокер)
    не останавливает обход остальных — исключение ловится на каждой
    компании отдельно, логируется под именем ``label`` (чтобы в логе было
    видно, какой диспетчер запнулся) и попадает в ``failed`` результата.
    Сбой ВЫПОЛНЕНИЯ самой ``task`` для одной компании сюда не относится —
    это уже отдельный воркер-процесс, и его падение остальных компаний не
    касается в принципе.

    Возвращает ``{"dispatched": [slug, ...], "failed": [slug, ...]}`` —
    списки, а не счётчики: удобно и для мониторинга, и для тестов.
    """
    from apps.companies.interface import active_company_slugs

    dispatched: list[str] = []
    failed: list[str] = []
    for slug in active_company_slugs():
        try:
            task.delay(company_slug=slug)
        except Exception:
            logger.exception(
                "%s: не удалось поставить задачу для company_slug=%s",
                label, slug,
            )
            failed.append(slug)
        else:
            dispatched.append(slug)

    logger.info("%s dispatched=%s failed=%s", label, dispatched, failed)
    return {"dispatched": dispatched, "failed": failed}
