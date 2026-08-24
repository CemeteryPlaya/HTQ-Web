"""Экспозиция метрик для Prometheus.

Три вещи, которые тесты стерегут, и каждая уже ломалась бы молча:

* **эндпоинт вообще есть** — джоб ``django-backend`` в prometheus.yml держали
  закомментированным именно потому, что его не было;
* **его не гасит гейт сервисов** — наблюдаемость обязана переживать
  выключение любого домена, иначе в аварии, когда домен и выключили,
  метрик как раз и не окажется;
* **метрики HTTP реально пишутся** — middleware-пара обнимает весь список, и
  перестановка в MIDDLEWARE ломает замер незаметно.
"""
from __future__ import annotations

import pytest
from django.test import Client

from apps.core.models import ServiceStatus


@pytest.mark.django_db
def test_metrics_endpoint_answers_in_prometheus_text_format():
    resp = Client().get("/metrics")
    assert resp.status_code == 200
    # Prometheus разбирает ответ по content-type; text/plain с version=0.0.4 —
    # то, что отдаёт choose_encoder на пустой/текстовый Accept.
    assert "text/plain" in resp["Content-Type"]
    assert b"# HELP" in resp.content


@pytest.mark.django_db
def test_both_slash_spellings_are_registered():
    """``APPEND_SLASH = False``: редиректа не будет, каждое написание
    обязано отвечать само."""
    assert Client().get("/metrics").status_code == 200
    assert Client().get("/metrics/").status_code == 200


@pytest.mark.django_db
def test_http_metrics_are_actually_collected():
    """Счётчик запросов растёт — значит middleware-пара на месте и в нужном
    порядке. Проверяем ростом, а не наличием строки: незарегистрированная
    метрика тоже «есть» в выводе, но всегда нулевая."""
    client = Client()
    client.get("/health/")
    first = client.get("/metrics").content.decode()
    assert "django_http_responses_total_by_status" in first

    client.get("/health/")
    second = client.get("/metrics").content.decode()

    def _total(dump: str) -> float:
        return sum(
            float(line.rsplit(" ", 1)[1])
            for line in dump.splitlines()
            if line.startswith("django_http_responses_total_by_status")
            and not line.startswith("#")
        )

    assert _total(second) > _total(first)


def test_database_and_cache_wrappers_are_wired_in_base_settings():
    """Движки-обёртки объявлены в БОЕВЫХ настройках.

    Проверяется именно ``settings.base``, а не текущее соединение: тестовый
    модуль намеренно переопределяет DATABASES на штатный postgresql и CACHES
    на locmem (htqweb/settings/test.py), поэтому под тестами обёрток нет и
    быть не должно. Подмена движка тихая — приложение ведёт себя одинаково с
    обёрткой и без неё, — так что откат этой строки иначе никто не заметит,
    пока в проде не исчезнут метрики БД.
    """
    from htqweb.settings import base

    assert base.DATABASES["default"]["ENGINE"] == (
        "django_prometheus.db.backends.postgresql")
    assert base.CACHES["default"]["BACKEND"] == (
        "django_prometheus.cache.backends.redis.RedisCache")


def test_prometheus_middleware_brackets_the_whole_stack():
    """Before — первой, After — последней. Любая перестановка сужает окно
    замера, и латентность занижается молча."""
    from htqweb.settings import base

    assert base.MIDDLEWARE[0] == (
        "django_prometheus.middleware.PrometheusBeforeMiddleware")
    assert base.MIDDLEWARE[-1] == (
        "django_prometheus.middleware.PrometheusAfterMiddleware")


@pytest.mark.django_db
def test_business_metrics_are_discovered_across_apps():
    """Автодискавери находит metrics.py доменных аппок.

    Аппки владеют своими метриками сами — кросс-доменный импорт моделей
    запрещён (test_app_isolation), поэтому общий сборщик их только собирает.
    """
    from apps.core import metrics as business

    collected = business.collect_all()
    assert "core" in collected                # реестр сервисов
    assert {"tasks", "approvals", "mail"} <= set(collected)


@pytest.mark.django_db
def test_business_metrics_reach_the_endpoint_through_the_cache():
    """Сбор и экспорт развязаны кэшем: считает Celery-beat, отдаёт вьюха."""
    from apps.core import metrics as business
    from apps.core.tasks import collect_business_metrics

    collect_business_metrics()
    assert business.load(), "задача не положила метрики в кэш"

    dump = Client().get("/metrics").content.decode()
    assert "htqweb_service_enabled" in dump
    assert "htqweb_tasks" in dump


@pytest.mark.django_db
def test_collector_does_no_io_while_the_registry_is_being_walked(monkeypatch):
    """Коллектор обязан только разворачивать готовый снимок.

    Регрессия на дедлок: кэш обёрнут django-prometheus и на каждом
    ``cache.get`` инкрементит ``django_cache_get_total``. Чтение кэша внутри
    ``collect()`` меняло реестр во время его же обхода, и процесс вставал
    намертво — на ASGI намертво, на WSGI незаметно (там мультипроцессный
    реестр пишет в файлы, а не в общий объект), поэтому и всплыло только в
    одном из двух процессов.

    Проверяем прямо: во время сбора кэш недоступен, а метрики всё равно
    собираются — значит ввода-вывода в ``collect()`` нет.
    """
    from django.core.cache import cache

    from apps.core import metrics as business
    from apps.core.tasks import collect_business_metrics

    collect_business_metrics()
    business.refresh()          # снимок берётся ДО обхода — так и задумано

    def explode(*args, **kwargs):
        raise AssertionError("collect() полез в кэш во время обхода реестра")

    monkeypatch.setattr(cache, "get", explode)
    families = list(business.BusinessMetricsCollector().collect())

    assert families, "снимок был, а метрик не собралось"


@pytest.mark.django_db
def test_empty_cache_exports_nothing_rather_than_zeros():
    """«Сборщик умер» и «ноль задач» обязаны выглядеть по-разному: молчание
    против нулевой линии. Иначе вставший beat читается как штиль."""
    from django.core.cache import cache

    from apps.core import metrics as business

    cache.delete(business.CACHE_KEY)
    dump = Client().get("/metrics").content.decode()
    assert "htqweb_tasks" not in dump
    # Технические метрики при этом на месте — отвалилась только бизнес-часть.
    assert "django_http_responses_total_by_status" in dump


@pytest.mark.django_db
def test_a_failing_app_collector_does_not_sink_the_rest(
        monkeypatch, fallback_log_mode):
    """Сбор — это диагностика; «нет ничего, потому что в одной аппке
    ошибка» — худший исход из возможных.

    Прод-режим подмен здесь обязателен (фикстура ``fallback_log_mode``), и
    это не обход строгого режима, а суть проверки: терпимость к упавшему
    сборщику нужна ИМЕННО на проде. У разработчика она, наоборот, снята —
    ``fallback`` поднимает ``FallbackNotAllowed``, и сломанный сборщик видно
    сразу; за это отвечает соседний тест.
    """
    from apps.core import metrics as business
    from apps.tasks import metrics as tasks_metrics

    def boom():
        raise RuntimeError("подсчёт задач упал")

    monkeypatch.setattr(tasks_metrics, "collect", boom)
    collected = business.collect_all()

    assert "tasks" not in collected
    assert "mail" in collected and "core" in collected


@pytest.mark.django_db
def test_a_failing_app_collector_is_loud_for_developers(monkeypatch):
    """Обратная сторона предыдущего теста: в строгом режиме (машина
    разработчика, тесты) упавший сборщик не заминается, а падает — иначе
    автор узнал бы о нём по дырке на графике неделю спустя."""
    from apps.core import metrics as business
    from apps.tasks import metrics as tasks_metrics
    from htqweb.fallback import FallbackNotAllowed

    def boom():
        raise RuntimeError("подсчёт задач упал")

    monkeypatch.setattr(tasks_metrics, "collect", boom)
    with pytest.raises(FallbackNotAllowed) as info:
        business.collect_all()

    # Причина сохранена целиком — она и есть ответ на вопрос «почему».
    assert isinstance(info.value.__cause__, RuntimeError)


@pytest.mark.django_db
def test_metrics_survive_a_disabled_service():
    """ServiceGateMiddleware гейтит только ``/api/<домен>/`` и ``/ws/``.
    Метрики лежат в корне намеренно: выключенный домен не должен уносить с
    собой наблюдаемость всего процесса."""
    ServiceStatus.objects.update_or_create(
        app_label="tasks", defaults={"enabled": False})
    # Домен действительно выключен...
    assert Client().get("/api/tasks/v1/projects/").status_code == 503
    # ...а метрики по-прежнему отдаются.
    assert Client().get("/metrics").status_code == 200
