"""Межаппный интерфейс модуля БЗО (для tasks, notifications и tender).

Каждая функция первой строкой зовёт ``require_service("bpp")`` — кроме
``register_request_listener``: её зовут из ``ready()``, когда базы ещё нет
(приём ``project.interface.register_change_listener``).

Схемы стыка с тендерным модулем (пакет B-1, ``schemas/tender.py``)
реэкспортируются отсюда: ``apps.tender`` импортирует только этот модуль
(сторож изоляции).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from apps.bpp.schemas.tender import (
    BudgetArticle,
    BudgetFigures,
    CounterpartyRef,
    ProspectIn,
    RequestRef,
    RequestStatusOut,
    TenderActor,
    TenderItemIn,
    TenderPartIn,
    TenderRequestSubmit,
)
from apps.core.services import require_service

__all__ = [
    "BudgetArticle", "BudgetFigures", "CounterpartyRef", "ProspectIn", "RequestRef",
    "RequestStatusOut", "TenderActor", "TenderItemIn", "TenderPartIn", "TenderRequestSubmit",
    "agreement_brief", "budget_articles", "budget_available",
    "cancel_requests_from_tender", "closing_docs_pending_for_user", "counterparty_brief",
    "create_counterparty_from_prospect",
    "find_by_number", "migrated_targets", "register_request_listener", "release_to_plan",
    "request_status", "search_agreements", "search_counterparties",
    "submit_request_from_tender", "upsert_counterparty_from_1c", "visible_agreement_brief",
    "withdraw_requests_from_tender",
]


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
    M-5): ``{id строкой: {id, number, status, counterparty_id, is_annex}}``,
    и только это (``is_annex`` — допсоглашение, к нему не привлекают). Невозможные и несуществующие ключи в ответ не попадают. Зовётся в
    контексте компании. Подмодуль ``bpp_agreements`` выключен — ``ServiceDisabled``."""
    require_service("bpp")
    require_service("bpp_agreements")
    from apps.bpp.services.agreements import neighbour

    return neighbour.brief(ids)


def visible_agreement_brief(ids, *, token, company: str | None) -> dict[str, dict]:
    """``agreement_brief`` только по договорам, которые ``token`` вправе видеть
    (как карточка договора, `agreements.can_view`); невидимый — как несуществующий. Для проверки
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
    допсоглашения), с учётом прав ``token`` на договоры — как карточка (`agreements.can_view`);
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


# ── заявка тендерного модуля (пакет B-1, T1.2; мастер-план tender T-07, T-09) ──
#
# Зовутся в контексте компании; пользователь — ``actor`` (``TenderActor``):
# права и группы статей БЗО — его собственные (T-20). Ошибки — штатный
# ``htqweb.errors.DomainError`` модуля БЗО. Подмодуль ``bpp_requests``
# выключен у компании — ``ServiceDisabled``.

def submit_request_from_tender(data: TenderRequestSubmit) -> list[RequestRef]:
    """Части заявки tender → ЗЗ ``source="tender"`` и их отправка, одной
    транзакцией: новая ЗЗ (``bpp_request_id=None``) или пересборка
    существующей («Черновик»/«На доработке»), затем BR-011 под блокировкой
    строки бюджета. Ошибка любой части откатывает все; у ``DomainError`` —
    ``details={"part": key}``."""
    require_service("bpp")
    require_service("bpp_requests")
    from apps.bpp.services.requests import tender

    return tender.submit_from_tender(data)


def withdraw_requests_from_tender(ids, *, actor: TenderActor) -> None:
    """Отозвать ЗЗ «На согласовании» (без решений); прочие — без изменений."""
    require_service("bpp")
    require_service("bpp_requests")
    from apps.bpp.services.requests import tender

    tender.withdraw_from_tender(ids, actor=actor)


def cancel_requests_from_tender(ids, *, actor: TenderActor, comment: str) -> None:
    """Черновик/доработка — отмена; утверждённая — «Закрыть остаток»; на
    согласовании — 409 ``E-STS-01``; отклонённая/отменённая/закрытая — пропуск."""
    require_service("bpp")
    require_service("bpp_requests")
    from apps.bpp.services.requests import tender

    tender.cancel_from_tender(ids, actor=actor, comment=comment)


def release_to_plan(ids, *, actor: TenderActor) -> None:
    """«Тендер не состоялся»: снять ``source`` с утверждённых ЗЗ — их позиции
    видны в Плане закупок у исполнителя. Не «Утверждена» — 409 ``E-STS-01``."""
    require_service("bpp")
    require_service("bpp_requests")
    from apps.bpp.services.requests import tender

    tender.release_to_plan(ids, actor=actor)


def request_status(ids) -> dict[str, RequestStatusOut]:
    """``{id ЗЗ: RequestStatusOut}`` по ЗЗ, заведённым tender; невозможные и
    чужие ключи в ответ не попадают."""
    require_service("bpp")
    require_service("bpp_requests")
    from apps.bpp.services.requests import tender

    return tender.request_status(ids)


def register_request_listener(fn: Callable[[RequestStatusOut], None]) -> None:
    """Подписать соседа на смену статуса ЗЗ ``source="tender"``: ``fn`` зовётся
    в транзакции смены (старт, утверждение, отказ, возврат, отзыв, отмена,
    закрытие остатка); исключение ``fn`` откатывает и саму смену. Звать из
    ``ready()`` — без ``require_service``."""
    from apps.bpp.services.requests import listeners

    listeners.add(fn)


def budget_available(project_id, article_id, *, actor: TenderActor,
                     role: Literal["sn", "pm"]) -> BudgetFigures:
    """Лимит, «Задействовано» и остаток статьи по действующей версии бюджета —
    в правах ``actor`` в роли ``role``, как у заявки: роль не назначена — 403,
    ПМ и чужой проект — 403 ``E-REQ-05`` (BR-014), статья чужой группы — 403
    ``E-REQ-04`` (BR-010); нет утверждённого бюджета — ``E-BUD-02``, нет
    строки — ``E-BUD-07``."""
    require_service("bpp")
    require_service("bpp_requests")
    from apps.bpp.services.requests import tender

    return tender.budget_available(project_id, article_id, actor=actor, role=role)


def budget_articles(project_id, *, actor: TenderActor,
                    role: Literal["sn", "pm"]) -> list[BudgetArticle]:
    """Статьи утверждённого бюджета проекта из группы роли ``role`` (BR-010),
    с остатком. Роль не назначена — 403."""
    require_service("bpp")
    require_service("bpp_requests")
    from apps.bpp.services.requests import tender

    return tender.budget_articles(project_id, actor=actor, role=role)


def create_counterparty_from_prospect(data: ProspectIn, *, actor: TenderActor) -> CounterpartyRef:
    """Карточка контрагента по реквизитам потенциального поставщика тендера
    (T5.4): совпадение страна + рег. номер — найденная карточка
    (``created=False``), иначе новая «Активен» правами закупщика (узел
    ``bpp.counterparties`` create, иначе 403). Нет рег. номера, карточка
    заблокирована или в архиве — 422 ``E-TND-14``."""
    require_service("bpp")
    from apps.bpp.services.requests import tender_counterparty

    return tender_counterparty.create_from_prospect(data, actor=actor)
