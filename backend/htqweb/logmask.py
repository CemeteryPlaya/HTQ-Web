"""Маскировка секретов в путях, попадающих в логи.

Токен ссылки портала поставщика живёт прямо в пути
(``/api/tender/v1/supplier/<token>/…``, страница ``/supplier/<token>``), а
Django пишет путь каждого ответа 4xx/5xx в логгер ``django.request``
(``Forbidden: /api/…``), dev-сервер — каждый запрос в ``django.server``.
Оттуда строки уходят в stdout и Loki. Шлюз маскирует токен в своём журнале
(``$tender_portal_uri`` в nginx), а этот фильтр — в логах бэкенда: он стоит
на консольном обработчике (всё, что печатается) и на самих логгерах
``django.request``/``django.server`` (там запись рождается, и её видит
любой обработчик, в том числе ``caplog`` тестов).
"""

from __future__ import annotations

import logging
import re

#: Сегмент пути после префикса — секрет, вместо него ``***``.
_SECRET_PATH = re.compile(r"(/supplier/)[^/\s?#\"']+")


def mask(text: str) -> str:
    return _SECRET_PATH.sub(r"\1***", text)


class MaskSecretPaths(logging.Filter):
    """Переписывает сообщение записи, если в нём есть секрет из пути.
    Запись не отбрасывается никогда."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 — кривой формат не наша забота: пусть печатается как есть
            return True
        masked = mask(message)
        if masked != message:
            record.msg, record.args = masked, ()
        return True
