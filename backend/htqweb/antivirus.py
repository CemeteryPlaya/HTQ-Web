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

Срок (этап 8, D-S8-1). ``ANTIVIRUS_TIMEOUT`` — на ВСЮ проверку файла, а не
на каждую операцию сокета: крайний срок ``time.monotonic() + ANTIVIRUS_TIMEOUT``
ставится один раз, а перед каждой операцией (подключение, каждый ``sendall``,
каждый ``recv``) остаток считается заново, проверяется (≤ 0 — «не успели»,
``ScanUnavailable``) и только потом уходит в ``settimeout``. С таймаутом «на
операцию» clamd, отдающий ответ по байту чуть быстрее таймаута, держал бы
воркер сколько угодно; а отрицательный остаток в ``settimeout`` — это
``ValueError``, не ``OSError``, то есть 500 без метрики вместо 503.

Ответ clamd на ``z``-команду всегда кончается ``\\0``. Ответ без него
(соединение закрыто раньше, срок вышел посреди чтения) — неполный и не
разбирается: обрезанное «stream: OK» — не «чисто».

Известное ограничение: разрешение имени (``getaddrinfo`` внутри
``socket.create_connection``) таймаутом сокета не ограничено — срок начинает
действовать с подключения, — и ``create_connection`` выдаёт остаток КАЖДОМУ
найденному адресу целиком: при N адресах худший случай — срок плюс DNS плюс
(N−1)·срок. В compose имя ``clamav`` разрешает внутренний DNS Docker в один
адрес, поэтому на практике это миллисекунды; зависший резолвер хоста срок
проверки не остановит.
"""

from __future__ import annotations

import socket
import struct
import time
from dataclasses import dataclass

from django.conf import settings

#: Кусок потока. clamd принимает любые; 64 КБ — чтобы не копировать 20 МБ разом.
CHUNK = 64 * 1024

#: Предел ответа clamd: строка вердикта — десятки байт; больше — не clamd.
MAX_REPLY = 4096


class ScanUnavailable(Exception):
    """Сканер настроен, но проверить файл не смог — принимать его нельзя."""


@dataclass(frozen=True)
class Verdict:
    clean: bool
    signature: str = ""


def enabled() -> bool:
    return bool(getattr(settings, "ANTIVIRUS_CLAMD_HOST", ""))


def scan(data: bytes) -> Verdict:
    """Проверить байты. ``ScanUnavailable`` — сеть, срок проверки или ``ERROR``.

    Срок ``ANTIVIRUS_TIMEOUT`` — на всю проверку (см. докстринг модуля).
    """
    host = settings.ANTIVIRUS_CLAMD_HOST
    port = settings.ANTIVIRUS_CLAMD_PORT
    deadline = _Deadline(settings.ANTIVIRUS_TIMEOUT, host, port)
    try:
        with socket.create_connection((host, port),
                                      timeout=deadline.remaining()) as sock:
            _send(sock, deadline, b"zINSTREAM\0")
            view = memoryview(data)
            for start in range(0, len(view), CHUNK):
                chunk = view[start:start + CHUNK]
                _send(sock, deadline, struct.pack("!L", len(chunk)))
                _send(sock, deadline, chunk)
            _send(sock, deadline, struct.pack("!L", 0))
            reply = _read_reply(sock, deadline)
    except OSError as exc:
        raise ScanUnavailable(f"clamd {host}:{port} недоступен: {exc}") from exc
    return parse_reply(reply)


class _Deadline:
    """Крайний срок всей проверки; ``remaining()`` — остаток перед операцией."""

    def __init__(self, timeout: float, host: str, port: int) -> None:
        self.timeout = timeout
        self.at = time.monotonic() + timeout
        self.where = f"{host}:{port}"

    def remaining(self) -> float:
        """Остаток, считанный ОДИН раз и уже проверенный: всегда > 0.

        Не успели — ``ScanUnavailable`` (fail-closed); в ``settimeout`` уходит
        ровно проверенное значение, а не пересчитанное заново.
        """
        left = self.at - time.monotonic()
        if not left > 0:  # «не больше нуля» ловит и NaN от испорченной настройки
            raise ScanUnavailable(
                f"clamd {self.where} не проверил файл за {self.timeout:g} с")
        return left


def _send(sock: socket.socket, deadline: _Deadline, data) -> None:
    sock.settimeout(deadline.remaining())
    sock.sendall(data)


def parse_reply(reply: str) -> Verdict:
    if reply.endswith(" OK"):
        return Verdict(clean=True)
    if reply.endswith(" FOUND"):
        body = reply[:-len(" FOUND")]
        signature = body.split(": ", 1)[1] if ": " in body else body
        return Verdict(clean=False, signature=signature.strip())
    raise ScanUnavailable(f"clamd не проверил файл: {reply or 'пустой ответ'}")


def _read_reply(sock: socket.socket, deadline: _Deadline) -> str:
    """Ответ до завершающего ``\\0``; без него — ``ScanUnavailable``.

    Неполный буфер (соединение закрыто раньше ``\\0``) не разбирается:
    обрезанный ответ ничего не доказывает.
    """
    buffer = b""
    while not buffer.endswith(b"\0"):
        sock.settimeout(deadline.remaining())
        part = sock.recv(4096)
        if not part:
            raise ScanUnavailable(
                f"clamd {deadline.where} закрыл соединение, не дослав ответ")
        buffer += part
        if len(buffer) > MAX_REPLY:
            raise ScanUnavailable(
                f"clamd {deadline.where} прислал ответ длиннее {MAX_REPLY} байт")
    return buffer.rstrip(b"\0").decode("utf-8", "replace").strip()
