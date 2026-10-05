"""Раздел ежедневной сводки «Ждут от вас закрывающих документов» (A3.2, D-13).

Источник центра уведомлений поверх ``bpp.interface.closing_docs_pending_for_user``
(контракт §2.6, B3.2): счета автора в «Ждёт закрывающих документов». Регистрирует
его ``BppConfig.ready()`` — центр о модуле не знает, граф зависимостей идёт от
источника к центру (как у ``signoff``, ``holders.digest_items``).

Тенантный: счета лежат в схеме компании, сводка зовёт источник в контексте
каждой компании пользователя и сама делает ссылку абсолютной — на поддомен
компании (``notifications.services.digest._absolute``), поэтому здесь путь
остаётся относительным.
"""

from __future__ import annotations

SOURCE_KEY = "bpp.closing_docs"
SECTION = "Ждут от вас закрывающих документов"
# Реестр счетов на вкладке «Ждут закрывающих»: с этапа 4 вкладка открывается
# из адреса (`?tab=awaiting_docs`, InvoicesPage).
LANDING_URL = "/bpp/invoices?tab=awaiting_docs"


def closing_docs_items(user_id: int) -> list[dict]:
    """``[{title, url, since}]`` — пункт «СЧ-… — ждёт закрывающих N дн.».

    Выключенный у компании модуль (или подмодуль счетов) — не сбой источника,
    а «ждать нечего»: пустой список без ``ServiceDisabled``. Иначе сводка каждое
    утро писала бы ``notifications.digest.source_failed`` на каждого
    пользователя компании (Review Focus 5).
    """
    from apps.bpp import interface as bpp
    from apps.core.services import service_enabled

    # «bpp_invoices» — подмодуль: service_status проверяет и родителя «bpp».
    if not service_enabled("bpp_invoices"):
        return []
    return [{"title": row["title"], "url": row["url"], "since": row["since"]}
            for row in bpp.closing_docs_pending_for_user(user_id)]


def register() -> None:
    from apps.notifications import interface as notifications

    notifications.register_digest_source(
        SOURCE_KEY, closing_docs_items, tenant=True, section=SECTION,
        landing_url=LANDING_URL)
