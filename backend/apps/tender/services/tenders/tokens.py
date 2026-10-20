"""Токены ссылок поставщика (мастер-план T-21, план этапов 0–2, §4.2).

``secrets.token_urlsafe(32)`` — 256 бит случайности; в БД — только SHA-256
hex. Сырой токен живёт ровно один ответ (публикация, перевыпуск, приглашение
после публикации) и больше не восстанавливается: утечка таблицы не даёт
ни одной рабочей ссылки. Никогда не пишите токен в журнал, лог или ответ
карточки.
"""

from __future__ import annotations

import hashlib
import secrets

from apps.companies import interface as companies

SUPPLIER_PATH = "/supplier/"


def digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue() -> tuple[str, str]:
    """``(сырой токен, его хэш)``."""
    token = secrets.token_urlsafe(32)
    return token, digest(token)


def link(company: str | None, token: str) -> str:
    """Ссылка на портал на хосте компании (``companies.public_url``); без
    него — относительный путь: фронт достроит его своим хостом."""
    base = (companies.public_url(company) or "") if company else ""
    return f"{base.rstrip('/')}{SUPPLIER_PATH}{token}"
