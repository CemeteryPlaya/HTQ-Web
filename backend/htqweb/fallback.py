"""Подмена значения, которую слышно: единая точка для всех fallback'ов.

Fallback — место, где при отсутствии данных или при сбое подставляется
значение по умолчанию и выполнение продолжается. Каждый по отдельности
осмыслен, но все они молчаливы: на проде подмена выглядит как нормальная
работа, а разработчик узнаёт о ней, когда цифры на дашборде не сходятся.

Этот модуль делает их слышимыми, оставаясь невидимым для пользователя:
в теле ответа и в UI не меняется ничего, канал — только лог (stdout →
promtail → Loki) и метрика.

Два режима, ось — ``HTQ_ENV`` (см. ``settings/base.py``):

* ``log`` (production, staging) — подмена происходит, пишется строка
  ``FALLBACK …`` и растёт ``htqweb_fallback_total``;
* ``strict`` (development, тесты) — подмены НЕ происходит: летит
  ``FallbackNotAllowed``, чтобы автор увидел настоящую причину, а не её
  замаскированное следствие.

Как пользоваться. Конструкция ``try/except`` остаётся на месте, вызов идёт
внутри ``except`` — поток управления виден в коде, а не спрятан в декоратор
или контекстный менеджер::

    try:
        values = module.collect()
    except Exception as exc:
        fallback("core.metrics.app_collect", None,
                 reason="сбор метрик аппки упал", exc=exc, app=label)
        continue

``site`` — СТАТИЧЕСКИЙ литерал вида ``<аппка>.<модуль>.<что>``. Он уходит в
метку метрики, поэтому подставлять туда значения из данных нельзя: разнесёт
кардинальность. По той же причине переменная часть кладётся в ``**context``
(она идёт только в лог, в метрику не попадает).

``expected=True`` — единственная лазейка: штатная деградация, у которой нет
«настоящей причины» («у дня нет шаблона — берём дефолтный»). Такая подмена
не роняет strict-режим, пишется уровнем INFO и живёт в счётчике с меткой
``expected="true"``. Всё остальное — ``expected=False`` по умолчанию.

⚠️ Метрику отдают только ``backend-web`` и ``backend-asgi``: Celery-процессы
``/metrics`` не публикуют (Prometheus снимает их через Flower), поэтому
подмены внутри задач видны ТОЛЬКО в логах. Их закрывает отдельное
Loki-правило по подстроке ``FALLBACK`` (infra/logging/grafana-provisioning/
alerting/rules.yml) — без него дыра была бы незаметной.
"""
from __future__ import annotations

import logging
from typing import Any, TypeVar

from django.conf import settings
from prometheus_client import Counter

# Отдельный логгер, а не ``__name__``-логгер аппки: уровень и приёмник
# fallback'ов крутятся независимо от ``apps``/``django`` (FALLBACK_LOG_LEVEL),
# и по имени их видно в Loki одним селектором.
logger = logging.getLogger("htqweb.fallback")

T = TypeVar("T")

STRICT = "strict"
LOG = "log"

# Счётчик создаётся на импорте модуля — то есть ровно один раз на процесс
# (Python кэширует модули), поэтому защита от повторной регистрации не нужна.
# Под gunicorn'ом попадает в мультипроцессный режим автоматически: воркеры
# пишут в файлы PROMETHEUS_MULTIPROC_DIR, а собирает их вьюха /metrics.
fallback_total = Counter(
    "htqweb_fallback_total",
    "Срабатывания fallback-подмен по местам в коде",
    ["site", "expected"],
)


class FallbackNotAllowed(RuntimeError):
    """Подмена в среде, где fallback'и запрещены (``FALLBACK_MODE=strict``).

    Поднимается ``from`` исходного исключения, если оно было, — traceback
    настоящей причины сохраняется целиком.
    """


def mode() -> str:
    """``"log"`` или ``"strict"``. Читается на каждом вызове намеренно.

    Не кэшируется: ``override_settings`` в тестах должен работать, а цена
    чтения атрибута настроек ничтожна на фоне того, что происходит вокруг
    сработавшего fallback'а.
    """
    return settings.FALLBACK_MODE


def is_strict() -> bool:
    """Для редких мест, где ветвиться надо ДО того, как подменять."""
    return mode() == STRICT


def _context_suffix(context: dict[str, Any]) -> str:
    if not context:
        return ""
    return " " + " ".join(f"{key}={value!r}"
                          for key, value in sorted(context.items()))


def fallback(site: str, value: T, *, reason: str, expected: bool = False,
             exc: BaseException | None = None, **context: Any) -> T:
    """Зарегистрировать подмену и вернуть ``value`` (либо упасть в strict).

    :param site: статический идентификатор места, ``<аппка>.<модуль>.<что>``.
    :param value: то, что подставляется вместо настоящего значения.
    :param reason: человеческое объяснение — попадёт в лог и в исключение.
    :param expected: штатная деградация (см. докстринг модуля).
    :param exc: исходное исключение, если подмена случилась в ``except``.
    :param context: переменные детали для лога (в метрику НЕ идут).
    """
    fallback_total.labels(site=site,
                          expected="true" if expected else "false").inc()

    message = f"FALLBACK site={site} reason={reason}{_context_suffix(context)}"

    if expected:
        # Штатная деградация: она предусмотрена бизнес-логикой, и strict её
        # не роняет — иначе флаг пришлось бы обходить, а не соблюдать.
        logger.info(message)
        return value

    if mode() == STRICT:
        raise FallbackNotAllowed(
            f"{message} | подмена запрещена: FALLBACK_MODE=strict. Устраните "
            f"причину, а если это штатная деградация — пометьте вызов "
            f"fallback(..., expected=True)."
        ) from exc

    # exc_info с самим исключением, а не True: fallback часто вызывается уже
    # после выхода из except-блока, и sys.exc_info() там пуст.
    logger.warning(message, exc_info=exc)
    return value
