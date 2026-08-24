"""Хуки gunicorn, обслуживающие мультипроцессные метрики.

Проверяются отдельно от ``/metrics``, потому что проверить их через HTTP
нельзя: gunicorn на Windows не запускается вовсе (нужен ``fcntl``), а под
Linux хуки зовёт он сам, а не приложение. Логика при этом чистая и вполне
тестируемая — чем здесь и пользуемся.

Ошибка в любом из двух хуков не ломает приложение, а тихо портит цифры:
без очистки каталога счётчики умерших воркеров складываются с живыми и
метрики скачут вверх на ровном месте. Именно поэтому тесты есть.
"""
from __future__ import annotations

import os

import pytest

from htqweb import gunicorn_conf


def test_startup_clears_leftovers_from_the_previous_run(tmp_path, monkeypatch):
    """Файлы переживают рестарт контейнера, а MultiProcessCollector сложит
    их с новыми: метрики скакнут вверх без единого запроса."""
    stale = tmp_path / "counter_11.db"
    stale.write_bytes(b"stale")
    monkeypatch.setenv("PROMETHEUS_MULTIPROC_DIR", str(tmp_path))

    gunicorn_conf.on_starting(server=None)

    assert not stale.exists()
    # Каталог обязан остаться: воркеры пишут в него сразу после старта.
    assert tmp_path.is_dir()


def test_startup_recreates_a_missing_directory(tmp_path, monkeypatch):
    """tmpfs монтируется пустым, а на dev-машине каталога может не быть
    вовсе — в обоих случаях воркерам нужно, чтобы он существовал."""
    target = tmp_path / "run" / "prometheus"
    monkeypatch.setenv("PROMETHEUS_MULTIPROC_DIR", str(target))

    gunicorn_conf.on_starting(server=None)

    assert target.is_dir()


def test_hooks_do_nothing_without_the_env_var(tmp_path, monkeypatch, capsys):
    """Без переменной режим не мультипроцессный (dev-runserver, ASGI,
    тесты) — хуки обязаны быть безвредны, а не падать.

    Безвредны, но не молчаливы: под gunicorn'ом отсутствие переменной значит,
    что ``/metrics`` отдаёт цифры одного воркера из четырёх, и узнавать об
    этом по заниженным вчетверо графикам — худший из способов. Логгер здесь
    недоступен (конфиг читается до подъёма Django), поэтому строка печатается
    с тем же префиксом FALLBACK, что и остальные, — её ловит Loki-правило.
    """
    monkeypatch.delenv("PROMETHEUS_MULTIPROC_DIR", raising=False)
    keeper = tmp_path / "keep.db"
    keeper.write_bytes(b"x")

    gunicorn_conf.on_starting(server=None)
    gunicorn_conf.child_exit(server=None, worker=_Worker(pid=1234))

    assert keeper.exists(), "хук тронул каталог, к которому не имеет отношения"
    out = capsys.readouterr().out
    assert "FALLBACK site=htqweb.gunicorn.no_multiproc_dir" in out
    # child_exit молчит намеренно: он зовётся на каждый перезапуск воркера, и
    # та же строка оттуда превратилась бы в шум.
    assert out.count("FALLBACK") == 1


def test_child_exit_marks_the_dead_worker(tmp_path, monkeypatch):
    """Gunicorn перезапускает воркеров (таймаут, OOM, max-requests). Файл
    ушедшего иначе продолжит учитываться, и счётчики будут врать вверх."""
    monkeypatch.setenv("PROMETHEUS_MULTIPROC_DIR", str(tmp_path))
    gunicorn_conf.on_starting(server=None)

    marked: list[int] = []
    import prometheus_client.multiprocess as mp

    monkeypatch.setattr(mp, "mark_process_dead", marked.append)
    gunicorn_conf.child_exit(server=None, worker=_Worker(pid=4242))

    assert marked == [4242]


class _Worker:
    def __init__(self, pid: int) -> None:
        self.pid = pid
