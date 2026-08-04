"""Живой IMAP-клиент корпоративного почтового сервера.

До этого модуля в домене mail живого IMAP-подключения не существовало:
``services/sync/mailcow_imap.py`` умеет только распарсить УЖЕ полученные
байты письма (``parse_eml``), а подключение было объявлено непортируемым
seam'ом («нет достижимого IMAP-хоста»). Хост появился — это и есть тот самый
недостающий кусок.

Стандартная библиотека (``imaplib``), синхронно — как и весь остальной код
этого домена (``mailcow_client.py``, ``sender/*``): Django-вьюхи и
Celery-задачи здесь синхронные, тянуть asyncio-стек ради одного клиента
незачем. Новых зависимостей не добавляет.

Единственный живой сетевой вызов вынесен в seam-метод ``_open_connection``:
тесты монkeypatch'ят ровно его и работают на фейковом ``imaplib``-объекте,
без сети.

Доступ через SSH-туннель прозрачен: клиент просто подключается к
``IMAP_HOST:IMAP_PORT``, которыми в docker-compose назначен сервис
``mail-tunnel`` (``ssh -L``). Настройки TLS при этом обычно
``IMAP_SSL=false`` + ``IMAP_STARTTLS=true``: снаружи трафик шифрует SSH, а
STARTTLS добавляет шифрование на участке туннель→почтовый сервер, если
сервер его предлагает.
"""
from __future__ import annotations

import base64
import imaplib
import logging
import re
import ssl
from dataclasses import dataclass
from typing import Iterator

from django.conf import settings

log = logging.getLogger(__name__)

# imaplib по умолчанию режет ответы в 10 000 байт — письмо с вложением
# заметно больше. Тот же приём, что и у большинства IMAP-клиентов.
imaplib._MAXLINE = max(getattr(imaplib, "_MAXLINE", 10_000), 10_000_000)


class ImapError(RuntimeError):
    """Ошибка соединения/аутентификации/команды IMAP."""


class ImapNotConfigured(ImapError):
    """IMAP_HOST не задан — подключаться некуда."""


@dataclass(frozen=True)
class ImapConfig:
    host: str
    port: int = 993
    use_ssl: bool = True
    starttls: bool = False
    timeout: int = 30
    #: имя для проверки TLS-сертификата, если оно отличается от ``host``
    #: (TLS сквозь SSH-туннель — см. IMAP_TLS_SERVER_HOSTNAME)
    tls_server_hostname: str = ""

    @classmethod
    def from_settings(cls) -> "ImapConfig":
        """Эффективные реквизиты: настройки из интерфейса поверх env.

        Имя метода сохранено (его зовут все существующие вызывающие), но
        источником стал ``mail_config.get_config()`` — см. тот модуль про
        правило слияния «пустое в БД = берём из env».
        """
        from apps.mail.services.mail_config import get_config

        cfg = get_config()
        if not cfg.imap_host:
            raise ImapNotConfigured(
                "IMAP-хост не задан: укажите его на странице «Корпоративные ящики» "
                "(вкладка «Подключение») или переменной IMAP_HOST"
            )
        return cls(
            host=cfg.imap_host,
            port=cfg.imap_port,
            use_ssl=cfg.imap_ssl,
            starttls=cfg.imap_starttls,
            timeout=cfg.imap_timeout,
            tls_server_hostname=cfg.imap_tls_server_hostname,
        )


class _IMAP4_SSL_ServerName(imaplib.IMAP4_SSL):
    """``IMAP4_SSL``, проверяющий сертификат по ЗАДАННОМУ имени.

    Штатный ``IMAP4_SSL`` подставляет в ``server_hostname`` тот же адрес, к
    которому подключается. При TLS сквозь SSH-туннель это ``mail-tunnel``, а
    сертификат выписан на настоящее имя почтового сервера — проверка падает.
    Здесь имя для проверки задаётся отдельно, а сама проверка остаётся
    включённой (в отличие от «выключить верификацию», что убрало бы защиту
    от подмены).
    """

    def __init__(self, *args, server_hostname: str, **kwargs):
        self._server_hostname = server_hostname
        super().__init__(*args, **kwargs)

    def _create_socket(self, timeout=None):
        sock = imaplib.IMAP4._create_socket(self, timeout)
        return self.ssl_context.wrap_socket(sock, server_hostname=self._server_hostname)


def is_configured() -> bool:
    from apps.mail.services.mail_config import get_config

    return bool(get_config().imap_host)


# ── Кодирование имён папок (RFC 3501 modified UTF-7) ─────────────────────
#
# Кириллические папки («Отправленные», «Корзина») приезжают в LIST именно в
# этой кодировке. Полноценный кодек — в сторонней imapclient; здесь хватает
# декодера для отображения и «как есть» для ASCII-имён, которыми оперируют
# MAIL_SYNC_FOLDERS (INBOX/Sent/...).

def decode_folder(raw: str) -> str:
    """``&BB4EQgQ,BDIENQRABEIEMA-`` → «Отправленные».

    Модифицированный UTF-7: между ``&`` и ``-`` лежит base64 от UTF-16-BE,
    в котором ``/`` заменён на ``,``; ``&-`` — экранированный сам ``&``.
    ASCII-имена (INBOX, Sent) проходят насквозь.
    """
    def _chunk(match: re.Match) -> str:
        body = match.group(1)
        if not body:
            return "&"
        try:
            b64 = body.replace(",", "/")
            b64 += "=" * (-len(b64) % 4)
            return base64.b64decode(b64).decode("utf-16-be")
        except Exception:  # noqa: BLE001 — имя папки не стоит падения sync
            return match.group(0)

    return re.sub(r"&([A-Za-z0-9+,]*)-", _chunk, raw)


_LIST_RE = re.compile(rb'\((?P<flags>[^)]*)\)\s+"(?P<delim>[^"]*)"\s+(?P<name>.+)')


@dataclass
class FetchedMessage:
    """Одно письмо, снятое с сервера: сырые байты + серверные метаданные."""

    uid: int
    raw: bytes
    flags: tuple[str, ...]

    @property
    def is_read(self) -> bool:
        return "\\Seen" in self.flags

    @property
    def is_flagged(self) -> bool:
        return "\\Flagged" in self.flags


class ImapClient:
    """Тонкая обёртка над ``imaplib``. Используется как контекст-менеджер::

        with ImapClient.from_settings().login(addr, pwd) as imap:
            for msg in imap.fetch_since("INBOX", last_uid=42):
                ...
    """

    def __init__(self, config: ImapConfig) -> None:
        self.config = config
        self._conn: imaplib.IMAP4 | None = None
        self._selected: str | None = None

    @classmethod
    def from_settings(cls) -> "ImapClient":
        return cls(ImapConfig.from_settings())

    # ── соединение ───────────────────────────────────────────────────────

    def _open_connection(self) -> imaplib.IMAP4:
        """ЕДИНСТВЕННЫЙ живой сетевой вызов модуля — тесты подменяют его."""
        cfg = self.config
        if cfg.use_ssl:
            context = ssl.create_default_context()
            if cfg.tls_server_hostname and cfg.tls_server_hostname != cfg.host:
                return _IMAP4_SSL_ServerName(
                    cfg.host, cfg.port, timeout=cfg.timeout, ssl_context=context,
                    server_hostname=cfg.tls_server_hostname,
                )
            return imaplib.IMAP4_SSL(
                cfg.host, cfg.port, timeout=cfg.timeout, ssl_context=context,
            )
        conn = imaplib.IMAP4(cfg.host, cfg.port, timeout=cfg.timeout)
        if cfg.starttls:
            conn.starttls(ssl.create_default_context())
        return conn

    def login(self, username: str, password: str) -> "ImapClient":
        try:
            self._conn = self._open_connection()
            self._conn.login(username, password)
        except imaplib.IMAP4.error as exc:
            self._safe_close()
            raise ImapError(f"IMAP login failed for {username}: {exc}") from exc
        except (OSError, ssl.SSLError) as exc:
            self._safe_close()
            raise ImapError(f"IMAP connect failed ({self.config.host}:{self.config.port}): {exc}") from exc
        return self

    def __enter__(self) -> "ImapClient":
        return self

    def __exit__(self, *exc_info) -> None:
        self.logout()

    def logout(self) -> None:
        self._safe_close()

    def _safe_close(self) -> None:
        conn, self._conn, self._selected = self._conn, None, None
        if conn is None:
            return
        try:
            if self._selected:
                conn.close()
        except Exception:  # noqa: BLE001 — закрытие не должно ронять вызывающего
            pass
        try:
            conn.logout()
        except Exception:  # noqa: BLE001
            pass

    @property
    def conn(self) -> imaplib.IMAP4:
        if self._conn is None:
            raise ImapError("not connected — call login() first")
        return self._conn

    # ── команды ──────────────────────────────────────────────────────────

    def _check(self, result: tuple, command: str):
        typ, data = result
        if typ != "OK":
            detail = b" ".join(x for x in data if isinstance(x, bytes)).decode("utf-8", "replace")
            raise ImapError(f"IMAP {command} failed: {detail or typ}")
        return data

    def list_folders(self) -> list[str]:
        data = self._check(self.conn.list(), "LIST")
        folders: list[str] = []
        for line in data:
            if not isinstance(line, bytes):
                continue
            match = _LIST_RE.match(line)
            if not match:
                continue
            name = match.group("name").decode("utf-8", "replace").strip().strip('"')
            folders.append(decode_folder(name))
        return folders

    def select(self, folder: str, *, readonly: bool = True) -> dict:
        """SELECT + вычитывание UIDVALIDITY/UIDNEXT — они и есть курсор
        синхронизации, который ложится в ``EmailAccount.sync_state``."""
        self._check(self.conn.select(f'"{folder}"', readonly=readonly), f"SELECT {folder}")
        self._selected = folder

        state = {"uidvalidity": None, "uidnext": None}
        try:
            data = self._check(
                self.conn.status(f'"{folder}"', "(UIDVALIDITY UIDNEXT)"), "STATUS",
            )
            raw = b" ".join(x for x in data if isinstance(x, bytes)).decode("utf-8", "replace")
            for key in ("UIDVALIDITY", "UIDNEXT"):
                m = re.search(rf"{key}\s+(\d+)", raw)
                if m:
                    state[key.lower()] = int(m.group(1))
        except ImapError:
            # Некоторые серверы запрещают STATUS на уже выбранной папке —
            # синхронизация переживает это, просто без курсора.
            log.debug("imap_status_unavailable folder=%s", folder)
        return state

    def search_uids(self, *, since_uid: int | None = None) -> list[int]:
        """UID'ы писем в выбранной папке — строго больше ``since_uid``."""
        criteria = f"{since_uid + 1}:*" if since_uid else "1:*"
        data = self._check(self.conn.uid("SEARCH", None, "UID", criteria), "UID SEARCH")
        raw = b" ".join(x for x in data if isinstance(x, bytes))
        uids = [int(tok) for tok in raw.split() if tok.isdigit()]
        # `N:*` на пустом хвосте возвращает последнее письмо — отфильтровываем.
        if since_uid:
            uids = [u for u in uids if u > since_uid]
        return sorted(uids)

    def fetch(self, uid: int) -> FetchedMessage | None:
        """Забрать письмо целиком, НЕ трогая флаг \\Seen (BODY.PEEK)."""
        data = self._check(
            self.conn.uid("FETCH", str(uid), "(FLAGS BODY.PEEK[])"), f"UID FETCH {uid}",
        )
        raw: bytes | None = None
        meta = b""
        for part in data:
            if isinstance(part, tuple) and len(part) >= 2:
                meta += part[0] or b""
                raw = part[1]
            elif isinstance(part, bytes):
                meta += part
        if raw is None:
            return None
        flags = tuple(
            f.decode("ascii", "replace") for f in imaplib.ParseFlags(meta) or ()
        )
        return FetchedMessage(uid=uid, raw=raw, flags=flags)

    def fetch_since(
        self, folder: str, *, last_uid: int | None = None, limit: int = 200,
    ) -> Iterator[FetchedMessage]:
        """Итератор новых писем папки. Возвращает не больше ``limit`` штук —
        самых свежих (хвост списка UID)."""
        self.select(folder, readonly=True)
        uids = self.search_uids(since_uid=last_uid)
        # Хронологически (как и в sync): порция самых старых необработанных,
        # чтобы курсор двигался по одному письму и ничего не перепрыгивал.
        for uid in uids[:limit] if limit else uids:
            msg = self.fetch(uid)
            if msg is not None:
                yield msg

    def set_seen(self, folder: str, uids: list[int], *, seen: bool = True) -> int:
        """Толкнуть локальное «прочитано» обратно на сервер.

        Это вторая половина двусторонней синхронизации писем: ``fetch_*``
        тянет серверные флаги вниз, ``set_seen`` — локальные наверх.
        """
        if not uids:
            return 0
        self.select(folder, readonly=False)
        command = "+FLAGS" if seen else "-FLAGS"
        self._check(
            self.conn.uid("STORE", ",".join(str(u) for u in uids), command, "(\\Seen)"),
            "UID STORE",
        )
        return len(uids)


def verify_credentials(username: str, password: str) -> tuple[bool, str | None]:
    """Проверить пару логин/пароль живым IMAP-логином.

    Это и есть «создание ящика» для серверов без админ-API: сам ящик по IMAP
    завести нельзя (в протоколе нет такой команды), но можно убедиться, что
    он существует и учётка рабочая — и только тогда привязать его к
    пользователю платформы. Возвращает ``(ok, error)``; исключения не
    выпускает наружу.
    """
    try:
        client = ImapClient.from_settings()
    except ImapNotConfigured as exc:
        return False, str(exc)
    try:
        with client.login(username, password):
            return True, None
    except ImapError as exc:
        return False, str(exc)
    except Exception as exc:  # noqa: BLE001 — провижининг не должен падать 500
        return False, f"IMAP error: {exc}"
