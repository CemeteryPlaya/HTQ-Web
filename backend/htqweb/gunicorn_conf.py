"""Конфигурация gunicorn — существует ради мультипроцессных метрик.

``backend-web`` крутится как ``gunicorn --workers 4``. ``prometheus_client``
в таком режиме держит счётчики не в памяти процесса, а в файлах каталога
``PROMETHEUS_MULTIPROC_DIR`` — по файлу на живой процесс; собирает их
``MultiProcessCollector`` в ``apps.core.views.metrics``.

У этой схемы ровно два острых угла, и оба закрыты здесь:

* **Мусор от прошлого запуска.** Файлы переживают рестарт контейнера, и
  ``MultiProcessCollector`` радостно сложит счётчики умерших воркеров с
  живыми — метрики скакнут вверх на ровном месте. Каталог чистится на
  старте мастера (``on_starting``).
* **Мусор от умерших воркеров в течение жизни процесса.** Gunicorn
  перезапускает воркеров (таймаут, OOM, ``--max-requests``), и файл ушедшего
  так и останется учитываться. ``child_exit`` помечает его мёртвым — это
  единственный штатный способ, других хуков с pid ушедшего воркера у
  gunicorn нет.

Подключается флагом ``-c``; см. команду backend-web в docker-compose.yml.
Настройки самого gunicorn (bind/workers/timeout) остаются в команде — их
удобнее переопределять на месте, и они не имеют отношения к метрикам.
"""
from __future__ import annotations

import os
import shutil


def _multiproc_dir() -> str | None:
    return os.environ.get("PROMETHEUS_MULTIPROC_DIR")


def on_starting(server):
    """Мастер поднялся, воркеров ещё нет — самый безопасный момент чистить."""
    path = _multiproc_dir()
    if not path:
        # Единственное место в проекте, где подмена сообщается print'ом, а не
        # htqweb.fallback: конфиг gunicorn читается ДО того, как поднимется
        # окружение Django, и импорт настроек (а значит и режима fallback'ов)
        # здесь невозможен. Строка с тем же префиксом, что у остальных, —
        # её ловят и grep, и Loki-правило.
        # Только на старте мастера: в child_exit то же самое печаталось бы на
        # каждый перезапуск воркера и превратилось бы в шум.
        print("FALLBACK site=htqweb.gunicorn.no_multiproc_dir "
              "reason=PROMETHEUS_MULTIPROC_DIR не задан: /metrics отдаст "
              "цифры одного случайного воркера из нескольких", flush=True)
        return
    # Сносим каталог целиком, а не по файлу: в нём бывают и .db-файлы старых
    # версий prometheus_client, и они точно так же были бы просуммированы.
    shutil.rmtree(path, ignore_errors=True)
    os.makedirs(path, exist_ok=True)


def child_exit(server, worker):
    """Воркер ушёл — снять его файлы с учёта.

    Импорт внутри функции намеренно: конфиг gunicorn читается до того, как
    поднимется окружение Django, и тащить prometheus_client на уровень
    модуля значило бы падать на старте там, где метрик может и не быть.
    """
    if not _multiproc_dir():
        return
    from prometheus_client import multiprocess

    multiprocess.mark_process_dead(worker.pid)
