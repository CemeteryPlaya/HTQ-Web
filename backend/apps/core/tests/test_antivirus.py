"""Клиент clamd (``htqweb/antivirus.py``) против поддельного clamd.

Поддельный сервер говорит настоящим протоколом INSTREAM: принимает
``zINSTREAM\\0``, собирает поток из кусков с 4-байтной длиной и отвечает
строкой с нулём в конце. Так проверяется сама проводка (куски, завершающий
ноль, разбор ответа), а не заглушка на её месте, — без живого ClamAV,
которого в тестовом прогоне нет.
"""

from __future__ import annotations

import socket
import socketserver
import struct
import threading
import time

from types import SimpleNamespace

import pytest

from htqweb import antivirus

EICAR = rb"X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"


class _Clamd(socketserver.BaseRequestHandler):
    """Отвечает FOUND, если в потоке EICAR, иначе OK (или то, что велено)."""

    def handle(self):
        command = self.request.recv(len(b"zINSTREAM\0"))
        assert command == b"zINSTREAM\0", command
        stream = b""
        while True:
            header = self._exact(4)
            (size,) = struct.unpack("!L", header)
            if size == 0:
                break
            stream += self._exact(size)
        self.server.received.append(stream)
        reply = self.server.reply or (
            "stream: Win.Test.EICAR_HDB-1 FOUND" if EICAR in stream else "stream: OK")
        if self.server.drip is not None:
            self._drip(reply.encode(), *self.server.drip)
            return
        if self.server.no_terminator:
            self.request.sendall(reply.encode())  # без ``\0`` и сразу закрыть
            return
        self.request.sendall(reply.encode() + b"\0")

    def _drip(self, payload: bytes, interval: float, close_after: float) -> None:
        """Отдавать ответ по байту раз в ``interval`` без ``\\0``, закрыть через ``close_after``.

        Медленным сделан именно ОТВЕТ, а не приём потока: на Windows буферы
        loopback проглатывают весь поток сразу, и медленное чтение сервером
        клиента бы не задержало.
        """
        started = time.monotonic()
        try:
            for byte in payload:
                time.sleep(interval)
                self.request.sendall(bytes([byte]))
            time.sleep(max(0.0, close_after - (time.monotonic() - started)))
        except OSError:
            pass  # клиент ушёл по своему сроку — так и задумано

    def _exact(self, size: int) -> bytes:
        data = b""
        while len(data) < size:
            part = self.request.recv(size - len(data))
            if not part:
                raise ConnectionError("клиент оборвал поток")
            data += part
        return data


@pytest.fixture
def clamd(settings):
    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _Clamd)
    server.daemon_threads = True
    server.received = []
    server.reply = None
    server.drip = None  # (интервал, закрыть через) — «капающий» clamd
    server.no_terminator = False
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    settings.ANTIVIRUS_CLAMD_HOST = "127.0.0.1"
    settings.ANTIVIRUS_CLAMD_PORT = server.server_address[1]
    settings.ANTIVIRUS_TIMEOUT = 5
    yield server
    server.shutdown()
    server.server_close()


def test_clean_bytes_pass_and_arrive_whole(clamd):
    data = b"%PDF-1.4\n" + b"x" * (antivirus.CHUNK * 2 + 17)  # больше двух кусков

    verdict = antivirus.scan(data)

    assert verdict == antivirus.Verdict(clean=True)
    assert clamd.received == [data]


def test_eicar_is_found_with_its_signature(clamd):
    verdict = antivirus.scan(b"prefix " + EICAR)

    assert verdict.clean is False
    assert verdict.signature == "Win.Test.EICAR_HDB-1"


def test_clamd_error_is_not_clean(clamd):
    """``ERROR`` — clamd не смог проверить (размер, база): это не «чисто»."""
    clamd.reply = "INSTREAM size limit exceeded. ERROR"

    with pytest.raises(antivirus.ScanUnavailable, match="size limit"):
        antivirus.scan(b"data")


def test_unreachable_clamd_is_unavailable(settings):
    with socket.socket() as probe:  # свободный порт, на котором никто не слушает
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    settings.ANTIVIRUS_CLAMD_HOST = "127.0.0.1"
    settings.ANTIVIRUS_CLAMD_PORT = port
    settings.ANTIVIRUS_TIMEOUT = 2

    with pytest.raises(antivirus.ScanUnavailable, match="недоступен"):
        antivirus.scan(b"data")


def test_empty_host_disables_scanning(settings):
    settings.ANTIVIRUS_CLAMD_HOST = ""
    assert antivirus.enabled() is False
    settings.ANTIVIRUS_CLAMD_HOST = "clamav"
    assert antivirus.enabled() is True


@pytest.mark.parametrize("reply, verdict", [
    ("stream: OK", antivirus.Verdict(clean=True)),
    ("stream: Eicar-Signature FOUND", antivirus.Verdict(clean=False, signature="Eicar-Signature")),
])
def test_reply_parsing(reply, verdict):
    assert antivirus.parse_reply(reply) == verdict


def test_empty_reply_is_unavailable():
    with pytest.raises(antivirus.ScanUnavailable):
        antivirus.parse_reply("")


# ─── Срок — на всю проверку файла (этап 8, D-S8-1) ──────────────────────────
#
# ``ANTIVIRUS_TIMEOUT`` ограничивает ВСЮ проверку, а не каждую операцию сокета:
# иначе clamd, отдающий ответ по байту чуть быстрее таймаута, держал бы
# воркер сколько угодно долго (gunicorn --timeout 60 оборвал бы его раньше
# 503, и метрика ``unavailable`` не выросла бы).


def test_dripping_clamd_is_cut_off_by_the_whole_scan_deadline(clamd, settings):
    """Ответ по байту раз в 0,3·T без ``\\0``, закрытие через 3·T: ``< T + 1 с``.

    Каждый ``recv`` укладывается в T, поэтому таймаут «на операцию» ждал бы
    все ~3·T и разобрал бы неполный ответ «stream: OK» как «чисто».
    """
    timeout = 1.0
    settings.ANTIVIRUS_TIMEOUT = timeout
    clamd.drip = (0.3 * timeout, 3 * timeout)

    started = time.monotonic()
    with pytest.raises(antivirus.ScanUnavailable):
        antivirus.scan(b"%PDF-1.4 drip")
    elapsed = time.monotonic() - started

    assert elapsed < timeout + 1.0, elapsed


def test_dripping_clamd_is_refused_with_503_and_counted(clamd, settings):
    """Fail-closed: «не успели» — это 503 ``E-SYS-01`` и вердикт ``unavailable``."""
    from prometheus_client import REGISTRY

    from apps.media_files.services import upload_service
    from apps.media_files.services.scope_policy import ScopePolicy

    def unavailable() -> float:
        return REGISTRY.get_sample_value(
            "htqweb_antivirus_scans_total", {"verdict": "unavailable"}) or 0.0

    settings.ANTIVIRUS_TIMEOUT = 0.5
    clamd.drip = (0.15, 1.5)
    before = unavailable()

    with pytest.raises(upload_service.ScanUnavailable) as err:
        upload_service._scan(b"%PDF-1.4 drip", "a.pdf",
                             ScopePolicy(name="file_object", antivirus=True))

    assert err.value.status_code == 503
    assert unavailable() == before + 1


def test_reply_without_terminator_is_unavailable(clamd):
    """Ответ на ``z``-команду всегда кончается ``\\0``; без него — не разбирать."""
    clamd.no_terminator = True  # «stream: OK» и сразу закрыть соединение

    with pytest.raises(antivirus.ScanUnavailable, match="не дослав"):
        antivirus.scan(b"data")


def test_reply_without_terminator_found_is_not_parsed(clamd):
    """Даже обрезанное «FOUND» не разбирается: буфер без ``\\0`` неполный."""
    clamd.no_terminator = True

    with pytest.raises(antivirus.ScanUnavailable, match="не дослав"):
        antivirus.scan(EICAR)


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class _FakeSocket:
    """Сокет без сети: каждая операция «занимает» ``step`` секунд часов ``clock``.

    Пишет, какой таймаут ему ставили перед каждой операцией: так видно, что
    остаток считается от одного крайнего срока и до ``settimeout`` проверен.
    """

    def __init__(self, clock: _Clock, step: float, reply: list[bytes]) -> None:
        self.clock = clock
        self.step = step
        self.reply = list(reply)
        self.timeouts: list[float] = []
        self.ops: list[str] = []

    def settimeout(self, value):
        if value is not None and value < 0:
            raise ValueError("Timeout value out of range")  # как настоящий сокет
        self.timeouts.append(value)

    def sendall(self, data):
        self.ops.append("send")
        self.clock.now += self.step

    def recv(self, size):
        self.ops.append("recv")
        self.clock.now += self.step
        return self.reply.pop(0) if self.reply else b""

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


@pytest.fixture
def fake_net(monkeypatch, settings):
    """Подменённые часы и ``create_connection``; возвращает фабрику сценария."""
    settings.ANTIVIRUS_CLAMD_HOST = "clamav"
    settings.ANTIVIRUS_CLAMD_PORT = 3310
    settings.ANTIVIRUS_TIMEOUT = 10
    clock = _Clock()
    # Подмена — имени в модуле, а не самих ``time``/``socket``: иначе поддельные
    # часы увидели бы и потоки фейкового clamd соседних тестов.
    monkeypatch.setattr(antivirus, "time", SimpleNamespace(monotonic=clock))
    state = {}

    def arrange(*, connect_takes: float, step: float, reply: list[bytes]):
        sock = _FakeSocket(clock, step, reply)
        state["sock"] = sock
        state["connect_timeouts"] = []

        def create_connection(address, timeout=None, *args, **kwargs):
            state["connect_timeouts"].append(timeout)
            clock.now += connect_takes
            return sock

        monkeypatch.setattr(antivirus, "socket", SimpleNamespace(create_connection=create_connection))
        return state

    return arrange


def test_remaining_time_shrinks_and_expiry_is_unavailable_not_valueerror(fake_net):
    """T = 10, каждая операция — 3 с: остатки 10, 7, 4, 1, затем срок вышел."""
    state = fake_net(connect_takes=3, step=3, reply=[b"stream: OK\0"])

    with pytest.raises(antivirus.ScanUnavailable):
        antivirus.scan(b"x")  # один кусок: команда, длина, кусок, ноль, ответ

    assert state["connect_timeouts"] == [10]
    timeouts = state["sock"].timeouts
    assert timeouts == [7, 4, 1], timeouts
    assert all(value > 0 for value in timeouts)
    # после «1» — ни одной операции: четвёртый sendall получил бы остаток -2
    assert state["sock"].ops == ["send", "send", "send"]


def test_deadline_spent_on_connect_is_unavailable(fake_net):
    """Подключение съело весь срок: следующая операция не начинается."""
    state = fake_net(connect_takes=11, step=0, reply=[b"stream: OK\0"])

    with pytest.raises(antivirus.ScanUnavailable):
        antivirus.scan(b"x")

    assert state["sock"].timeouts == []
    assert state["sock"].ops == []


def test_remaining_exactly_zero_is_unavailable(fake_net):
    """Остаток ровно 0 — тоже «не успели»: ``settimeout(0)`` — неблокирующий режим."""
    state = fake_net(connect_takes=10, step=0, reply=[b"stream: OK\0"])

    with pytest.raises(antivirus.ScanUnavailable):
        antivirus.scan(b"x")

    assert 0 not in state["sock"].timeouts


def test_slow_reply_in_parts_is_cut_by_deadline(fake_net):
    """Ответ кусками, каждый ``recv`` по 2 с при T = 10: срок кончается в чтении."""
    parts = [bytes([b]) for b in b"stream: OK"]  # без ``\0``
    state = fake_net(connect_takes=0, step=0, reply=parts)
    sock = state["sock"]
    original_recv = sock.recv

    def slow_recv(size):
        sock.clock.now += 2
        return original_recv(size)

    sock.recv = slow_recv

    with pytest.raises(antivirus.ScanUnavailable):
        antivirus.scan(b"x")

    recv_timeouts = sock.timeouts[4:]  # первые четыре — перед sendall
    assert recv_timeouts == [10, 8, 6, 4, 2], sock.timeouts
    assert sock.ops.count("recv") == 5


def test_fast_reply_within_deadline_is_parsed(fake_net):
    """Быстрый ответ в пределах срока разбирается как раньше."""
    state = fake_net(connect_takes=1, step=1,
                     reply=[b"stream: Eicar-Signature FOUND\0"])

    verdict = antivirus.scan(b"x")

    assert verdict == antivirus.Verdict(clean=False, signature="Eicar-Signature")
    assert state["sock"].timeouts == [9, 8, 7, 6, 5]


def test_oversized_reply_is_unavailable(fake_net):
    """Строка вердикта clamd — десятки байт; бесконечный ответ без ``\0`` не копится."""
    fake_net(connect_takes=0, step=0, reply=[b"x" * (antivirus.MAX_REPLY + 1)])

    with pytest.raises(antivirus.ScanUnavailable, match="длиннее"):
        antivirus.scan(b"x")
