"""Ошибки модуля с текстами ТЗ §26.1.

Тексты с подстановками собираются здесь, а не по месту: так один раз и
дословно. Класс исключения — платформенный ``htqweb.errors.DomainError``.
"""

from __future__ import annotations

from zoneinfo import ZoneInfo

from django.conf import settings

from apps.users import interface as users
from htqweb.errors import DomainError

__all__ = ["DomainError", "check_version"]


def check_version(obj, expected: int | None) -> None:
    """Сверить версию документа из формы с текущей; устарела — E-CON-01.

    ``expected=None`` — клиент версию не прислал (старый клиент, служебный
    вызов): проверка не выполняется.
    """
    if expected is None or int(expected) == int(obj.version):
        return
    name = "другим пользователем"
    if obj.updated_by:
        briefs = users.get_users_brief([obj.updated_by])
        if briefs:
            name = f"пользователем {briefs[0]['full_name']}"
    # Время читает человек — в поясе платформы (PLATFORM_TIME_ZONE, Алматы),
    # а не в поясе хранения TIME_ZONE (UTC).
    zone = ZoneInfo(settings.PLATFORM_TIME_ZONE)
    when = obj.updated_at.astimezone(zone).strftime("%H:%M") if obj.updated_at else "—"
    raise DomainError(
        "E-CON-01",
        f"Документ изменён {name} в {when}. Ваши изменения не сохранены. "
        f"Обновите страницу и внесите их повторно.",
        status=409,
    )
