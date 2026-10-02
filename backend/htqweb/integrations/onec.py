"""Клиент OData 1С — заготовка интеграции (A7.3, D-38, D-S7-5).

Синхронизация не запускается: модуль даёт только транспорт и разбор. Адрес
публикации, учётная запись и пароль приходят из окружения
(``ONEC_ODATA_URL``/``ONEC_USER``/``ONEC_PASSWORD`` — на сервере из файла
секретов ``secrets/onec.env``), в код и в репозиторий не попадают.

Что гарантирует клиент:

* только ``https`` (``http`` — явным флагом для стенда), адрес с логином и
  паролем внутри (``https://user:pw@host``) отвергается, не повторяясь в тексте;
* ``verify=True``, ``follow_redirects=False`` — на редирект не идём, чтобы
  заголовок ``Authorization`` не уехал на чужой хост;
* раздельные таймауты, лимит размера ответа и числа страниц;
* пароль не попадает в ``repr``, логи и тексты исключений: он хранится только
  в объекте авторизации httpx, а сообщения об ошибках собираются из своих
  фиксированных фраз.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Iterator
from urllib.parse import urlsplit

import httpx

__all__ = [
    "CONFLICT", "CREATED", "OneCClient", "OneCConfigError", "OneCDisabled", "OneCError",
    "OneCODataError", "OneCUnavailable", "Outcome", "REJECTED", "UNCHANGED", "UPDATED",
    "odata_guid", "odata_literal",
]

CREATED, UPDATED, UNCHANGED, CONFLICT, REJECTED = (
    "created", "updated", "unchanged", "conflict", "rejected")

DEFAULT_TIMEOUT = 20.0
CONNECT_TIMEOUT = 5.0
DEFAULT_PAGE_SIZE = 100
DEFAULT_MAX_PAGES = 200
DEFAULT_MAX_BYTES = 10 * 1024 * 1024
_ERROR_TEXT_MAX = 300
_GUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_ENTITY_SET = re.compile(r"\w+")


class OneCError(Exception):
    """Базовая ошибка интеграции с 1С."""


class OneCDisabled(OneCError):
    """Интеграция выключена: адрес публикации не задан."""


class OneCConfigError(OneCError):
    """Адрес или параметры подключения недопустимы (не https, userinfo в адресе…)."""


class OneCUnavailable(OneCError):
    """1С недоступна или ответила неприемлемо: сеть, таймаут, отказ в доступе,
    редирект, слишком большой или нечитаемый ответ."""


class OneCODataError(OneCError):
    """1С ответила структурным ``odata.error``."""

    def __init__(self, message: str, code: str = "") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Outcome:
    """Итог обработки одной записи 1С (общий для upsert контрагентов и «Проектов»)."""

    status: str
    reason: str = ""
    object_id: str | None = None


# ── литералы $filter ────────────────────────────────────────────────────

def odata_literal(value) -> str:
    """Строковый литерал OData: кавычка внутри удваивается. Всё, что попадает в
    ``$filter`` из данных, проходит только через эту функцию или ``odata_guid``."""
    return "'" + str(value).replace("'", "''") + "'"


def odata_guid(value) -> str:
    """``guid'…'`` из строки-GUID; всё остальное — ``ValueError``."""
    text = str(value or "").strip()
    if not _GUID.fullmatch(text):
        raise ValueError("Ожидался GUID вида xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx.")
    return f"guid'{text.lower()}'"


def is_guid(value) -> bool:
    return bool(_GUID.fullmatch(str(value or "").strip()))


# ── клиент ──────────────────────────────────────────────────────────────

def _check_url(url: str, *, allow_http: bool) -> str:
    if not (url or "").strip():
        raise OneCDisabled("Адрес публикации 1С не задан (ONEC_ODATA_URL).")
    parts = urlsplit(url.strip())
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        raise OneCConfigError("Адрес 1С не должен содержать логин и пароль — они задаются "
                              "отдельно (ONEC_USER/ONEC_PASSWORD).")
    allowed = ("https", "http") if allow_http else ("https",)
    if parts.scheme not in allowed:
        raise OneCConfigError("Адрес 1С должен начинаться с https:// (http — только флагом "
                              "ONEC_ALLOW_HTTP для стенда).")
    if not parts.hostname:
        raise OneCConfigError("В адресе 1С нет имени сервера.")
    return url.strip().rstrip("/")


class OneCClient:
    """Читающий клиент OData 1С. Транспорт — параметр конструктора (тесты
    подставляют ``httpx.MockTransport``)."""

    def __init__(self, base_url: str, *, user: str = "", password: str = "",
                 timeout: float = DEFAULT_TIMEOUT, transport: httpx.BaseTransport | None = None,
                 allow_http: bool = False, page_size: int = DEFAULT_PAGE_SIZE,
                 max_pages: int = DEFAULT_MAX_PAGES, max_bytes: int = DEFAULT_MAX_BYTES) -> None:
        self.base_url = _check_url(base_url, allow_http=allow_http)
        self.user = user or ""
        self.page_size = max(1, int(page_size))
        self.max_pages = max(1, int(max_pages))
        self.max_bytes = max(1, int(max_bytes))
        self._http = httpx.Client(
            auth=httpx.BasicAuth(self.user, password or ""), verify=True,
            follow_redirects=False, transport=transport,
            timeout=httpx.Timeout(float(timeout), connect=CONNECT_TIMEOUT),
            headers={"Accept": "application/json"})

    @classmethod
    def from_settings(cls, *, transport: httpx.BaseTransport | None = None) -> "OneCClient":
        from django.conf import settings

        return cls(settings.ONEC_ODATA_URL, user=settings.ONEC_USER,
                   password=settings.ONEC_PASSWORD, timeout=settings.ONEC_TIMEOUT,
                   allow_http=getattr(settings, "ONEC_ALLOW_HTTP", False), transport=transport)

    def __repr__(self) -> str:
        return f"OneCClient(url={self.base_url!r}, user={self.user!r})"

    __str__ = __repr__

    def close(self) -> None:
        self._http.close()

    # ── запросы ─────────────────────────────────────────────────────────

    def _get(self, entity_set: str, params: dict) -> dict:
        if not _ENTITY_SET.fullmatch(entity_set or ""):
            raise ValueError("Недопустимое имя набора сущностей 1С.")
        url = f"{self.base_url}/{entity_set}"
        try:
            with self._http.stream("GET", url, params=params) as response:
                body = self._read_body(response)
                status = response.status_code
        except httpx.TimeoutException:
            raise OneCUnavailable("1С не ответила за отведённое время.") from None
        except httpx.HTTPError as exc:
            raise OneCUnavailable(f"1С недоступна ({type(exc).__name__}).") from None
        if 300 <= status < 400:
            raise OneCUnavailable("1С ответила перенаправлением — на редиректы не идём.")
        if status in (401, 403):
            raise OneCUnavailable("1С отклонила учётную запись (проверьте ONEC_USER и пароль).")
        data = self._parse(body)
        if status >= 400:
            error = data.get("odata.error") if isinstance(data, dict) else None
            if isinstance(error, dict):
                raise self._odata_error(error)
            raise OneCUnavailable(f"1С ответила ошибкой {status}.")
        if not isinstance(data, dict):
            raise OneCUnavailable("Ответ 1С не похож на OData.")
        if isinstance(data.get("odata.error"), dict):
            raise self._odata_error(data["odata.error"])
        return data

    def _read_body(self, response: httpx.Response) -> bytes:
        chunks, total = [], 0
        for chunk in response.iter_bytes():
            total += len(chunk)
            if total > self.max_bytes:
                raise OneCUnavailable("Ответ 1С больше допустимого размера.")
            chunks.append(chunk)
        return b"".join(chunks)

    @staticmethod
    def _parse(body: bytes):
        if not body:
            return {}
        try:
            return json.loads(body)
        except ValueError:
            raise OneCUnavailable("Ответ 1С не является JSON.") from None

    @staticmethod
    def _odata_error(error: dict) -> OneCODataError:
        message = error.get("message")
        if isinstance(message, dict):
            message = message.get("value")
        text = str(message or "ошибка OData")[:_ERROR_TEXT_MAX]
        return OneCODataError(text, str(error.get("code", ""))[:64])

    def iter_entities(self, entity_set: str, *, filter: str | None = None,
                      select: str | None = None) -> Iterator[dict]:
        """Записи набора по страницам ``$top``/``$skip``; страница короче
        ``page_size`` — последняя. Больше ``max_pages`` страниц — ошибка."""
        skip = 0
        for _ in range(self.max_pages):
            # Стабильный порядок — иначе $skip между страницами теряет и дублирует записи.
            params = {"$format": "json", "$orderby": "Ref_Key", "$top": self.page_size,
                      "$skip": skip}
            if filter:
                params["$filter"] = filter
            if select:
                params["$select"] = select
            rows = self._get(entity_set, params).get("value")
            if not isinstance(rows, list):
                raise OneCUnavailable("В ответе 1С нет списка записей.")
            yield from rows
            if len(rows) < self.page_size:
                return
            skip += self.page_size
        raise OneCUnavailable("Слишком много страниц в ответе 1С — чтение остановлено.")

    def read_one(self, entity_set: str, *, filter: str | None = None) -> dict | None:
        params = {"$format": "json", "$top": 1}
        if filter:
            params["$filter"] = filter
        rows = self._get(entity_set, params).get("value")
        if not isinstance(rows, list):
            raise OneCUnavailable("В ответе 1С нет списка записей.")
        return rows[0] if rows else None
