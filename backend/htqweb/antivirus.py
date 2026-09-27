"""Антивирусная проверка файлов — клиент clamd (ClamAV) по TCP.

ТЗ §21: «Антивирусная проверка при загрузке [Л]». Сканер — отдельный
контейнер ``clamav`` (compose), сюда байты приходят целиком и уходят в
clamd командой ``INSTREAM``: кусками с 4-байтной длиной в сетевом порядке,
нулевая длина — конец потока. Ответ — одна строка:

* ``stream: OK`` — чисто;
* ``stream: <сигнатура> FOUND`` — угроза;
* ``... ERROR`` — clamd не смог проверить (превышен ``StreamMaxLength``,
  сломалась база) — это НЕ «чисто».

Протокол простой и стабильный, поэтому клиент свой, а не пакет: лишняя
зависимость в закреплённом окружении ради сорока строк.

Кто решает, что проверять, — не здесь: ``apps.media_files`` зовёт проверку
для scope с ``ScopePolicy.antivirus`` (сейчас — ``file_object``, документы
ТЗ §21). Выключатель — ``ANTIVIRUS_CLAMD_HOST``: пустой — проверки нет
(тесты, стенд без контейнера). Это явная настройка, а не подмена, поэтому
через ``htqweb.fallback`` не проходит. Настроенный, но недоступный сканер —
``ScanUnavailable``: файл без проверки не принимается (fail-closed),
молча пропустить его значило бы, что проверка есть только на бумаге.
"""

from __future__ import annotations

import socket
import struct
from dataclasses import dataclass

from django.conf import settings

#: Кусок потока. clamd принимает любые; 64 КБ — чтобы не копировать 20 МБ разом.
CHUNK = 64 * 1024


class ScanUnavailable(Exception):
    """Сканер настроен, но проверить файл не смог — принимать его нельзя."""


@dataclass(frozen=True)
class Verdict:
    clean: bool
    signature: str = ""


def enabled() -> bool:
    return bool(getattr(settings, "ANTIVIRUS_CLAMD_HOST", ""))


def scan(data: bytes) -> Verdict:
    """Проверить байты. ``ScanUnavailable`` — сеть, таймаут или ``ERROR``."""
    host = settings.ANTIVIRUS_CLAMD_HOST
    port = settings.ANTIVIRUS_CLAMD_PORT
    try:
        with socket.create_connection((host, port),
                                      timeout=settings.ANTIVIRUS_TIMEOUT) as sock:
            sock.sendall(b"zINSTREAM\0")
            view = memoryview(data)
            for start in range(0, len(view), CHUNK):
                chunk = view[start:start + CHUNK]
                sock.sendall(struct.pack("!L", len(chunk)))
                sock.sendall(chunk)
            sock.sendall(struct.pack("!L", 0))
            reply = _read_reply(sock)
    except OSError as exc:
        raise ScanUnavailable(f"clamd {host}:{port} недоступен: {exc}") from exc
    return parse_reply(reply)


def parse_reply(reply: str) -> Verdict:
    if reply.endswith(" OK"):
        return Verdict(clean=True)
    if reply.endswith(" FOUND"):
        body = reply[:-len(" FOUND")]
        signature = body.split(": ", 1)[1] if ": " in body else body
        return Verdict(clean=False, signature=signature.strip())
    raise ScanUnavailable(f"clamd не проверил файл: {reply or 'пустой ответ'}")


def _read_reply(sock: socket.socket) -> str:
    buffer = b""
    while not buffer.endswith(b"\0"):
        part = sock.recv(4096)
        if not part:
            break
        buffer += part
    return buffer.rstrip(b"\0").decode("utf-8", "replace").strip()
