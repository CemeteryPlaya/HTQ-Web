"""Ошибки файловой подсистемы — в конверте модуля БЗО (мастер-план, D-28).

``{"detail", "code", "fields": [{"field", "message"}], "details"}``:
``detail`` — готовый текст для человека по правилу ТЗ §26 («что произошло,
почему и что делать; слово «Ошибка» без пояснения запрещено»), ``code`` — для
программы, ``fields`` — какие поля подсветить, ``details`` — данные для
интерфейса. Это конверт ТЗ ``{code, message, fields, details}`` с ``message``
под именем ``detail``: так ошибку читает любой клиент платформы, которому
известен только общий ``{"detail"}`` (ответ Q-C21 — «аддитивно к конверту»).

Каталог §26.1 кодов для файлов не содержит, поэтому заведены ``E-FIL-*``;
общие коды — из ТЗ (``E-CON-01``, ``E-ACC-01``, ``E-SYS-01`` «сервер
недоступен» — им отвечает недоступный антивирус). 401 (нет токена) и 503
выключенного сервиса остаются в общем формате платформы — их отдаёт
``htqweb.http.api_view``, а не подсистема.
"""

from __future__ import annotations

from django.http import JsonResponse

E_FORMAT = "E-FIL-01"       # 415 недопустимый формат / содержимое не совпадает
E_SIZE = "E-FIL-02"         # 413 превышен размер
E_QUOTA = "E-FIL-03"        # 409 превышено количество / «1 действующий» уже есть
E_REQUIRED = "E-FIL-04"     # 422 не приложен обязательный файл (отправка владельца)
E_NOT_FOUND = "E-FIL-05"    # 404 документ / объект не найден или не виден
E_LOCKED = "E-FIL-06"       # 409 менять файлы в текущем статусе нельзя
E_BAD_REQUEST = "E-FIL-07"  # 422 некорректный запрос
E_INFECTED = "E-FIL-08"     # 422 антивирус нашёл угрозу
E_UNAVAILABLE = "E-SYS-01"  # 503 сервер недоступен (ТЗ §26.1) — антивирус не ответил
E_CONFLICT = "E-CON-01"     # 409 изменено другим пользователем (ТЗ §26.1)
E_ACCESS = "E-ACC-01"       # 403 нет прав (ТЗ §26.1)


def envelope(code: str, message: str, *, fields: list[dict] | None = None,
             details: dict | None = None) -> dict:
    return {"detail": message, "code": code, "fields": fields or [],
            "details": details or {}}


class FilesError(Exception):
    """Отказ подсистемы: код ТЗ, HTTP-статус и готовый текст."""

    def __init__(self, code: str, status: int, message: str, *,
                 fields: list[dict] | None = None,
                 details: dict | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.status = status
        self.message = message
        self.fields = fields or []
        self.details = details or {}

    def body(self) -> dict:
        return envelope(self.code, self.message, fields=self.fields,
                        details=self.details)

    def response(self) -> JsonResponse:
        return JsonResponse(self.body(), status=self.status)


def not_found(message: str | None = None) -> FilesError:
    return FilesError(
        E_NOT_FOUND, 404,
        message or "Документ не найден. Возможно, он удалён или у вас нет к нему доступа.")


def bad_request(message: str, *, field: str | None = None,
                details: dict | None = None) -> FilesError:
    return FilesError(E_BAD_REQUEST, 422, message,
                      fields=[{"field": field, "message": message}] if field else None,
                      details=details)
