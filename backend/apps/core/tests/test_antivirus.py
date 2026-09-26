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
        self.request.sendall(reply.encode() + b"\0")

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
