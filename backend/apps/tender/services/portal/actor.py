"""Служебная учётка портала — «кто загрузил» у файлов КП поставщика (T3.4;
план этапа 3, §2 T3.4, Q-T10 умолчание).

Поставщик не пользователь платформы, а карточка файла требует автора
(ТЗ §21). Учётка ``tender-portal`` неактивна и без пароля
(``users.interface.ensure_service_account``); какое приглашение загрузило
файл — в журнале портала (``PortalEvent.meta``)."""

from __future__ import annotations

from apps.users import interface as users

USERNAME = "tender-portal"


def portal_actor() -> int:
    return users.ensure_service_account(USERNAME, first_name="Поставщик",
                                        last_name="(портал)")
