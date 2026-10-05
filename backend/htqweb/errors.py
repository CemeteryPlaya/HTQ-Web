"""Ошибка предметной области — отказ, который пользователь должен прочитать.

``detail`` — готовый текст для человека (у модуля БЗО — дословно из ТЗ §26.1),
``code`` — для машины (фронт по нему выбирает поведение), ``fields`` — какие
поля формы подсветить. Конверт аддитивен к платформенному ``{"detail": ...}``:
фронт, который читает только ``detail``, продолжает работать (решение Q-C21).
"""

from __future__ import annotations


class DomainError(Exception):
    def __init__(self, code: str, message: str, *, fields: list[dict] | None = None,
                 status: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.fields = list(fields or [])
        self.status = status

    def payload(self) -> dict:
        return {"detail": self.message, "code": self.code, "fields": self.fields}
