"""Бизнес-метрики платформы: сбор, хранение и экспорт.

Отвечает на вопросы, на которые технические метрики не отвечают: сколько
задач висит в работе, сколько согласований застряло, растёт ли очередь
неотправленной почты. Инфраструктура может быть идеально зелёной, пока
почта не уходит третьи сутки.

Три решения, которые определяют устройство модуля:

* **Метрики принадлежат аппкам, а не этому файлу.** Каждая аппка кладёт
  ``apps/<домен>/metrics.py`` с функцией ``collect()`` и обращается там к
  СВОИМ моделям. ``apps.core`` их только находит и складывает. Иначе
  пришлось бы импортировать чужие модели, а это прямой запрет
  (``apps/core/tests/test_app_isolation.py``) — и правильный: сбор метрик
  не повод дырявить границы доменов.

* **Считаем по расписанию, отдаём из кэша.** Гейдж, который лезет в БД на
  каждом скрейпе, при интервале 15 c и четырёх воркерах gunicorn'а даёт
  пачку одинаковых запросов в минуту и, что хуже, не работает в
  мультипроцессном режиме: там процесс-экспортёр вообще не тот, что считал.
  Поэтому цифры считает Celery-beat (``apps.core.tasks.collect_business_metrics``)
  и кладёт в Redis, а экспорт читает готовое.

* **Отсутствие данных — это отсутствие данных.** Если задача ни разу не
  отработала или кэш пуст, метрики просто не экспортируются, вместо того
  чтобы показать нули. Ноль задач и «сборщик умер» на графике обязаны
  выглядеть по-разному.

**Тенантные аппки (``settings.TENANT_APPS``) собираются веером по компаниям.**
Их ``collect()`` читает модели напрямую, а модели живут в схеме компании
(``co_<slug>``): вне контекста компании запрос ушёл бы в ``public``. Поэтому
сборщик зовёт ``collect()`` tenant-аппки внутри ``use_company(slug)`` для
КАЖДОЙ действующей компании и размечает её серии меткой ``company`` (слаг) —
решение заказчика 24.09.2026: алерт обязан называть компанию. Дашборды сводят
серии ``sum/max without (company)`` с переменной «Компания».

Компания без физической схемы пропускается (``logger.info``, не
``fallback``): ``search_path`` в несуществующую схему молча проваливается в
``public``, и такая «компания» отдала бы цифры ``public`` под своим именем —
на стенде до ``tenancy_bootstrap`` каждая из них. Падение ``collect()`` в
одной компании — ``fallback`` на эту компанию, остальные собираются.
"""
from __future__ import annotations

import logging
from typing import Callable

from django.apps import apps as django_apps
from django.conf import settings
from django.core.cache import cache
from django.utils.module_loading import module_has_submodule
from prometheus_client.core import GaugeMetricFamily

from htqweb.fallback import fallback

logger = logging.getLogger(__name__)

CACHE_KEY = "htqweb:business-metrics"
# Чуть больше периода сбора (60 с): переживает один пропущенный запуск, но
# не даёт показывать вчерашние цифры, если сборщик встал совсем.
CACHE_TTL = 180

# Снимок предыдущей утренней сводки — чтобы показывать «31 (−4)», а не голое
# «31». Отдельный ключ и отдельный TTL: основному нужна СВЕЖЕСТЬ (180 с),
# этому — ПАМЯТЬ на сутки, это противоположные требования.
#
# ⚠️ Redis запущен с maxmemory 128 МБ и allkeys-lru, то есть ключ могут
# вытеснить. Это не авария: сводка тогда выйдет без дельт, и так и задумано —
# лучше цифры без сравнения, чем сравнение с выдуманным вчера.
DIGEST_BASELINE_KEY = "htqweb:business-metrics:digest-baseline"
DIGEST_BASELINE_TTL = 3 * 24 * 3600     # переживает один пропущенный выпуск

# Префикс всех бизнес-метрик. Отдельный от django_* намеренно: по нему
# удобно фильтровать «наше предметное» против «технического».
PREFIX = "htqweb"

# Метка компании у серий tenant-аппок. Значение — слаг (не псевдоним
# поддомена): по слагу живут схема, claim токена и роли.
COMPANY_LABEL = "company"


def _metric_modules() -> list[tuple[str, object, bool]]:
    """``[(app_label, модуль metrics, тенантная ли аппка)]`` для аппок,
    которые его объявили.

    Тот же приём автодискавери, что у ``API_PREFIX`` в ``htqweb/urls.py``:
    добавление метрик новой аппке не требует правок здесь.
    """
    found = []
    tenant_apps = set(settings.TENANT_APPS)
    for config in django_apps.get_app_configs():
        if not config.name.startswith("apps."):
            continue
        if config.label == "core":          # свои метрики core не собирает
            continue
        if not module_has_submodule(config.module, "metrics"):
            continue
        module = __import__(f"{config.name}.metrics", fromlist=["metrics"])
        if callable(getattr(module, "collect", None)):
            found.append((config.label, module, config.label in tenant_apps))
            continue
        # Модуль есть, а функции нет — это опечатка в имени или недописанный
        # файл, и молча пропустить его значит потерять метрики целой аппки
        # без единого следа.
        fallback("core.metrics.module_without_collect", None,
                 reason="apps/<домен>/metrics.py без функции collect()",
                 app=config.label)
    return found


def _metric_companies() -> list[str]:
    """Слаги действующих компаний, у которых есть схема (см. докстринг модуля)."""
    from apps.companies.interface import active_company_slugs, schema_exists

    slugs = []
    for slug in active_company_slugs():
        if schema_exists(slug):
            slugs.append(slug)
        else:
            logger.info(
                "business metrics: у компании %r нет схемы — её tenant-метрики "
                "не считаются (штатно до tenancy_bootstrap; после — осиротевшая "
                "строка реестра)", slug,
            )
    return slugs


def _add_company(merged: dict, name: str, spec, slug: str) -> None:
    """Дописать серии одной компании в общую метрику, метка ``company`` — первой."""
    if isinstance(spec, (int, float)):
        spec = {"values": [((), spec)]}
    target = merged.setdefault(name, {
        "help": spec.get("help"),
        "labels": [COMPANY_LABEL, *spec.get("labels", [])],
        "values": [],
    })
    target["values"].extend(((slug, *labels), number)
                            for labels, number in spec.get("values", []))


def _collect_tenant(label: str, module, slugs: list[str]) -> dict:
    from htqweb.tenancy.db import use_company

    merged: dict = {}
    for slug in slugs:
        try:
            with use_company(slug):
                values = module.collect()
        except Exception as exc:
            fallback("core.metrics.tenant_collect_failed", None,
                     reason="сбор бизнес-метрик тенантной аппки в компании упал",
                     exc=exc, app=label, company=slug)
            continue
        for name, spec in (values or {}).items():
            _add_company(merged, name, spec, slug)
    return merged


def _core_metrics() -> dict:
    """Метрики самого реестра сервисов.

    Единственное, что core считает сам: выключенный домен — предметный
    факт, который объясняет разом и просевший трафик, и тишину в очереди,
    и его надо видеть на дашборде рядом с последствиями.
    """
    from apps.core.models import KNOWN_SERVICES
    from apps.core.services import service_enabled

    return {
        "service_enabled": {
            "help": "Домен включён в реестре (1) или выключен (0)",
            "labels": ["service"],
            "values": [((name,), 1 if service_enabled(name) else 0)
                       for name in KNOWN_SERVICES],
        },
    }


def collect_all() -> dict[str, dict]:
    """Опросить все аппки. Вызывается из Celery-задачи, не из экспорта.

    Падение одной аппки (или одной компании у tenant-аппки) не должно
    уносить метрики остальных: сбор — это диагностика, и «нет ничего,
    потому что в задачах ошибка» — худший из возможных исходов. В строгом
    режиме (машина разработчика, тесты) эта терпимость намеренно снимается —
    ``fallback`` поднимет исключение, и сломанный сборщик будет видно сразу,
    а не по дырке на графике.
    """
    result: dict[str, dict] = {"core": _core_metrics()}
    slugs: list[str] | None = None
    for label, module, tenant in _metric_modules():
        if tenant:
            if slugs is None:
                slugs = _metric_companies()
            values = _collect_tenant(label, module, slugs)
        else:
            try:
                values = module.collect()
            except Exception as exc:
                fallback("core.metrics.app_collect_failed", None,
                         reason="сбор бизнес-метрик аппки упал",
                         exc=exc, app=label)
                continue
        if values:
            result[label] = values
    return result


def store(values: dict[str, dict]) -> None:
    cache.set(CACHE_KEY, values, CACHE_TTL)


def load() -> dict[str, dict]:
    values = cache.get(CACHE_KEY)
    if values:
        return values
    # Штатно ровно в одном случае — первую минуту после старта, пока
    # Celery-beat не отработал ни разу. Дальше это уже «сборщик встал», но
    # различить их здесь нечем: и там и там кэш пуст. Поэтому expected=True
    # (strict-режим не роняет), а тревогу поднимает не этот код, а отсутствие
    # htqweb_*-метрик на дашборде — оно как раз ни на что не похоже.
    return fallback("core.metrics.cache_empty", {},
                    reason="кэш бизнес-метрик пуст: beat ещё не считал "
                           "или сборщик встал",
                    expected=True)


# Снимок, который отдаёт коллектор. Живёт отдельно от кэша НАМЕРЕННО — см.
# ``refresh`` ниже.
_snapshot: dict[str, dict] = {}


def refresh() -> dict[str, dict]:
    """Прочитать кэш и запомнить снимок для следующего сбора.

    ⚠️ Вызывать ТОЛЬКО вне обхода реестра (вьюха делает это до генерации).

    Коллектору запрещён любой ввод-вывод, и это не стилистика, а лечение
    дедлока: кэш обёрнут ``django_prometheus`` и на каждом ``cache.get``
    инкрементит ``django_cache_get_total``. Чтение кэша ВНУТРИ ``collect()``
    означало бы мутацию реестра во время его же обхода — процесс вставал
    намертво. На WSGI это не воспроизводилось (там мультипроцессный реестр
    пишет в файлы, а не в общий объект), поэтому ловилось только на ASGI.
    """
    global _snapshot
    _snapshot = load()
    return _snapshot


class BusinessMetricsCollector:
    """Разворачивает снимок в метрики Prometheus.

    Формат значения аппки: ``{"имя_метрики": {"help": str, "labels": [...],
    "values": [(кортеж_меток, число), ...]}}`` либо просто
    ``{"имя_метрики": число}`` для метрики без меток.

    Ничего не читает и не вызывает — только разворачивает то, что уже лежит
    в ``_snapshot`` (см. ``refresh``).

    ⚠️ Дефолты ``spec.get(...)`` ниже — единственные подмены в проекте, которые
    НЕ проходят через ``htqweb.fallback``, и намеренно. Во-первых, ``fallback``
    инкрементит свой счётчик, то есть менял бы реестр во время его же обхода —
    ровно то, от чего лечится ``refresh`` выше. Во-вторых, в строгом режиме он
    поднял бы исключение внутри генератора Prometheus, и вместо внятной ошибки
    разработчик получил бы сломанный ``/metrics``. Кривой spec — ошибка аппки,
    и ловить её надо там, где он собирается, а не там, где рисуется.
    """

    def collect(self):
        for app_label, metrics in _snapshot.items():
            for name, spec in metrics.items():
                metric_name = f"{PREFIX}_{name}"
                if isinstance(spec, (int, float)):
                    family = GaugeMetricFamily(
                        metric_name, f"{name} ({app_label})")
                    family.add_metric([], float(spec))
                    yield family
                    continue

                labels = list(spec.get("labels", []))
                family = GaugeMetricFamily(
                    metric_name,
                    spec.get("help") or f"{name} ({app_label})",
                    labels=labels,
                )
                for label_values, number in spec.get("values", []):
                    family.add_metric(
                        [str(v) for v in label_values], float(number))
                yield family


_registered = False


def register(registry) -> None:
    """Подключить коллектор к реестру ровно один раз.

    Повторная регистрация в prometheus_client — исключение, а модуль
    импортируется и вьюхой, и тестами.
    """
    global _registered
    if _registered:
        return
    registry.register(BusinessMetricsCollector())
    _registered = True
