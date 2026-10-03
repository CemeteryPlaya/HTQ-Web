"""Эксплуатация антивируса (A7.4, D-31): метрика вердиктов и проверка clamd.

Метрика ``htqweb_antivirus_scans_total{verdict}`` нужна, чтобы включённый, но
мёртвый сканер был виден не только по 503 у пользователей. Отказ при этом
остаётся отказом: молчащий сканер файл не пропускает (fail-closed).
"""

from __future__ import annotations

import socket
import threading

import pytest
from prometheus_client import REGISTRY

from apps.core import infrastructure
from apps.core.tests.test_antivirus import EICAR, clamd  # noqa: F401  (фикстура)
from apps.media_files.services import upload_service
from apps.media_files.services.scope_policy import ScopePolicy


def _count(verdict: str) -> float:
    return REGISTRY.get_sample_value(
        "htqweb_antivirus_scans_total", {"verdict": verdict}) or 0.0


POLICY = ScopePolicy(name="file_object", antivirus=True)


def test_clean_verdict_is_counted(clamd):  # noqa: F811
    before = _count("clean")
    upload_service._scan(b"%PDF-1.4 ok", "a.pdf", POLICY)
    assert _count("clean") == before + 1


def test_infected_verdict_is_counted_and_refused(clamd):  # noqa: F811
    before = _count("infected")
    with pytest.raises(upload_service.FileInfected):
        upload_service._scan(EICAR, "bad.pdf", POLICY)
    assert _count("infected") == before + 1


def test_silent_socket_is_unavailable_and_refused(settings):
    """Сокет принимает соединение и молчит: таймаут — ``unavailable``, 503."""
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    held = []
    threading.Thread(target=lambda: held.append(srv.accept()), daemon=True).start()
    settings.ANTIVIRUS_CLAMD_HOST = "127.0.0.1"
    settings.ANTIVIRUS_CLAMD_PORT = srv.getsockname()[1]
    settings.ANTIVIRUS_TIMEOUT = 0.3
    before = _count("unavailable")
    try:
        with pytest.raises(upload_service.ScanUnavailable) as err:
            upload_service._scan(b"x", "a.pdf", POLICY)
        assert err.value.status_code == 503
    finally:
        srv.close()
    assert _count("unavailable") == before + 1


def test_disabled_scanner_counts_nothing(settings):
    settings.ANTIVIRUS_CLAMD_HOST = ""
    before = {v: _count(v) for v in ("clean", "infected", "unavailable")}
    upload_service._scan(b"x", "a.pdf", POLICY)
    assert {v: _count(v) for v in before} == before


def test_scope_without_antivirus_counts_nothing(clamd):  # noqa: F811
    before = _count("clean")
    upload_service._scan(b"x", "a.png", ScopePolicy(name="avatar"))
    assert _count("clean") == before


# ── PING для панели инфраструктуры ──────────────────────────────────────

def test_ping_check_absent_when_host_empty(settings):
    settings.ANTIVIRUS_CLAMD_HOST = ""
    assert "clamav" not in infrastructure.active_checks()


def test_ping_green_on_pong(settings):
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)

    def serve():
        conn, _ = srv.accept()
        assert conn.recv(16) == b"zPING\0"
        conn.sendall(b"PONG\0")
        conn.close()

    threading.Thread(target=serve, daemon=True).start()
    settings.ANTIVIRUS_CLAMD_HOST = "127.0.0.1"
    settings.ANTIVIRUS_CLAMD_PORT = srv.getsockname()[1]
    check = infrastructure.active_checks()["clamav"]
    try:
        assert check() == ("ok", "PONG")
    finally:
        srv.close()


def test_ping_red_without_answer(settings):
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    port = srv.getsockname()[1]
    srv.close()  # порт закрыт
    settings.ANTIVIRUS_CLAMD_HOST = "127.0.0.1"
    settings.ANTIVIRUS_CLAMD_PORT = port
    result = infrastructure.run_health("clamav")
    assert result["status"] == "error"


def test_ping_red_on_wrong_reply(settings):
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)

    def serve():
        conn, _ = srv.accept()
        conn.recv(16)
        conn.sendall(b"secret-looking-banner\0")
        conn.close()

    threading.Thread(target=serve, daemon=True).start()
    settings.ANTIVIRUS_CLAMD_HOST = "127.0.0.1"
    settings.ANTIVIRUS_CLAMD_PORT = srv.getsockname()[1]
    status, message = infrastructure.active_checks()["clamav"]()
    srv.close()
    assert status == "error"
    assert "secret-looking" not in message  # содержимое ответа не раскрываем


# ── правка ревью ────────────────────────────────────────────────────────

def test_all_verdict_series_are_created_when_scanner_is_used(clamd, monkeypatch):  # noqa: F811
    """Первый отказ должен быть виден ``increase()``: серии рождаются нулями."""
    created = []

    class Recorder:
        def labels(self, verdict):
            created.append(verdict)

            class Child:
                def inc(self):
                    pass
            return Child()

    monkeypatch.setattr(upload_service, "antivirus_scans_total", Recorder())
    monkeypatch.setattr(upload_service, "_labels_ready", False)
    upload_service._scan(b"x", "a.pdf", POLICY)
    assert {"clean", "infected", "unavailable"} <= set(created)


def test_series_are_not_created_while_scanner_is_disabled(settings, monkeypatch):
    created = []

    class Recorder:
        def labels(self, verdict):
            created.append(verdict)

    settings.ANTIVIRUS_CLAMD_HOST = ""
    monkeypatch.setattr(upload_service, "antivirus_scans_total", Recorder())
    monkeypatch.setattr(upload_service, "_labels_ready", False)
    upload_service._scan(b"x", "a.pdf", POLICY)
    assert created == []


def test_health_history_includes_clamav_only_when_enabled(settings, monkeypatch):
    monkeypatch.setattr(infrastructure, "_ring_read", lambda key: [])
    settings.ANTIVIRUS_CLAMD_HOST = ""
    assert "clamav" not in infrastructure.health_history()["history"]
    settings.ANTIVIRUS_CLAMD_HOST = "clamav"
    assert "clamav" in infrastructure.health_history()["history"]
