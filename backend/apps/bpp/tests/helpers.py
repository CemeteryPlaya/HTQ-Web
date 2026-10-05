"""Помощники тестов модуля БЗО.

Запрос к ручке модуля — это токен с claim ``company`` + заголовок компании +
роль с нужным узлом (без роли гейт модуля отдаёт 403 всем, кроме
суперпользователя; CLAUDE.md, «Модель прав — одна»).
"""

from __future__ import annotations

from apps.access.tests.helpers import assign, token

__all__ = ["assign", "auth"]


def auth(slug: str, *, user_id: int = 7, **claims) -> dict:
    tok = token(user_id=user_id, sub=str(user_id), company=slug, **claims)
    return {"HTTP_AUTHORIZATION": f"Bearer {tok}", "HTTP_X_HTQ_COMPANY": slug}
