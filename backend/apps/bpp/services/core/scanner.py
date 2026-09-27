"""Антивирусная проверка файлов — задел (Q-B25, D-31).

``settings.BPP_FILE_SCANNER`` — путь к функции ``(data, filename) -> str |
None`` (строка — причина отказа). Не задан — проверки нет. ClamAV
подключается задачей A7.4 реализацией этой функции, без правки модуля.
"""

from __future__ import annotations

from django.conf import settings
from django.utils.module_loading import import_string

from htqweb.errors import DomainError


def scan(data: bytes, filename: str) -> None:
    path = getattr(settings, "BPP_FILE_SCANNER", "")
    if not path:
        return
    reason = import_string(path)(data, filename)
    if reason:
        raise DomainError("E-FILE-04", f"Файл «{filename}» не принят: {reason}.", status=422)
