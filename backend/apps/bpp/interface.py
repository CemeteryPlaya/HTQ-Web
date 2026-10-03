"""Межаппный интерфейс модуля БЗО (для tasks и notifications).

Каждая функция первой строкой зовёт ``require_service("bpp")``.
"""

from __future__ import annotations

from apps.core.services import require_service


def closing_docs_pending_for_user(user_id: int) -> list[dict]:
    """Счета автора в «Ждёт закрывающих документов» — для раздела ежедневной
    сводки (контракт §2.6, A3.2, D-13): ``[{invoice_id, number, title, url,
    since, days}]``. Зовётся в контексте компании."""
    require_service("bpp")
    from apps.bpp.services.invoices import payments

    return payments.closing_docs_pending_for_user(user_id)


def find_by_number(number: str) -> dict | None:
    """Счёт по системному номеру ``СЧ-ГГГГ-NNNNNN`` — для сверки выписки
    (контракт §2.6, A4.2): ``{id, number, status, amount, currency_code,
    counterparty_reg_number, paid_bank_amount, recon_status}`` или ``None``."""
    require_service("bpp")
    from apps.bpp.services.invoices import read

    return read.find_by_number(number)


def counterparty_brief(ids) -> dict[str, dict]:
    """Контрагенты батчем — для карточки партнёра ``tasks`` (A6.1):
    ``{id строкой: {id, name, short_name, reg_number, country_code, status,
    contact_person, phone, email, legal_address}}``. Несуществующие и
    невозможные ключи в ответ не попадают — ошибка это или нет, решает
    сосед. Зовётся в контексте компании."""
    require_service("bpp")
    from apps.bpp.services.counterparties import lookup

    return lookup.neighbour_cards(ids)


def search_counterparties(query: str | None, *, limit: int = 20) -> list[dict]:
    """Поиск контрагентов для выбора в чужой форме (партнёр ``tasks``,
    A6.1): по наименованию или БИН/ИИН, только «Активен» (статуса «Новый» в
    справочнике нет — контрагент заводится сразу действующим, D-20).
    Карточки — как у ``counterparty_brief``. Зовётся в контексте компании."""
    require_service("bpp")
    from apps.bpp.services.counterparties import lookup, service

    return [lookup.neighbour_card(cp) for cp in service.search_active(query, limit=limit)]


def migrated_targets(source_type: str, source_ids) -> dict[str, list[dict]]:
    """Куда переехали записи ``contracts`` (B6.1) — для заморозки старого
    раздела (A6.2): карточка показывает «перенесён в ДГ-…». ``{ключ записи
    строкой: [{target_type, target_id, number}]}``; неперенесённых в ответе
    нет. Зовётся в контексте компании."""
    require_service("bpp")
    from apps.bpp.services.migration import links

    return links.targets(source_type, source_ids)


def upsert_counterparty_from_1c(record: dict):
    """Один контрагент из 1С — идемпотентно (заготовка A7.3, D-38): ``Outcome``
    (``created|updated|unchanged|conflict|rejected``). В контексте компании."""
    require_service("bpp")
    from apps.bpp.services.counterparties import onec

    return onec.upsert_counterparty(record)


def agreement_brief(ids) -> dict[str, dict]:
    """Договоры батчем — для привлечения партнёра ``tasks`` (хвост этапа 6,
    M-5): ``{id строкой: {id, number, status, counterparty_id}}``, и только
    это. Невозможные и несуществующие ключи в ответ не попадают. Зовётся в
    контексте компании. Подмодуль ``bpp_agreements`` выключен — ``ServiceDisabled``."""
    require_service("bpp")
    require_service("bpp_agreements")
    from apps.bpp.services.agreements import neighbour

    return neighbour.brief(ids)


def visible_agreement_brief(ids, *, token, company: str | None) -> dict[str, dict]:
    """``agreement_brief`` только по договорам, которые ``token`` вправе видеть
    (как в реестре договоров); невидимый — как несуществующий. Для проверки
    при привязке в чужой форме. Подмодуль ``bpp_agreements`` выключен —
    ``ServiceDisabled``."""
    require_service("bpp")
    require_service("bpp_agreements")
    from apps.bpp.services.agreements import neighbour

    return neighbour.visible_brief(ids, token=token, company=company)


def search_agreements(query: str | None, *, partner_key, token,
                      company: str | None, limit: int = 20) -> list[dict]:
    """Поиск договоров контрагента для выбора в чужой форме (привлечение
    партнёра ``tasks``): только «Действует»/«Исполнен», основные (не
    допсоглашения), с учётом прав ``token`` на договоры — как в реестре;
    без права — пусто. Строки: ``{id, number, status, counterparty_id, name,
    ext_number, ext_date}``. Подмодуль ``bpp_agreements`` выключен у компании —
    пустой список. Зовётся в контексте компании."""
    require_service("bpp")
    from apps.core.services import ServiceDisabled

    try:
        require_service("bpp_agreements")
    except ServiceDisabled:
        return []
    from apps.bpp.services.agreements import neighbour

    return neighbour.search(query, counterparty_id=partner_key, token=token,
                            company=company, limit=limit)
