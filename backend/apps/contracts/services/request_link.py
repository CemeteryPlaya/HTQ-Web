"""Связь документа contracts с заявкой конструктора «Запросы».

Одобренная заявка на закуп (``apps.approvals``) исполняется договором или
счётом без договора. Документ ссылается на неё голым ``request_id`` (FK
через границу аппки запрещён), а всё, что про заявку нужно знать —
существует ли, одобрена ли, под какую строку бюджета, — спрашивается у
``apps.approvals.interface``, ровно как договор спрашивает про строку у
собственного ``budget_calc``.

Правило одно и строгое: **договор по заявке заключается на ту же строку
бюджета, под которую заявку одобрили.** Заявку согласовывали под
конкретный карман; договор из другого кармана обесценил бы согласование,
а хранить на документе «строку заявки» отдельно от его собственной значило
бы завести две версии правды о деньгах (тот же довод, что у
``Agreement.budget_line`` против пары «администратор + программа»).

Что НЕ проверяется здесь намеренно: суммы. В заявке на закуп суммы нет
(ТРУ / количество / единица / дата потребности), цену узнают уже у
поставщика — её проверяет ``budget_calc.check_capacity`` по остатку строки.

``ServiceDisabled`` от approvals не глушится: документ ПО заявке нельзя
завести, пока некому подтвердить, что заявка одобрена; документ БЕЗ заявки
approvals не трогает вовсе.
"""

from __future__ import annotations

from apps.approvals import interface as approvals

APPROVED = "approved"


class RequestLinkViolation(Exception):
    """Документ ссылается на заявку, по которой его заводить нельзя."""


def check_request_link(request_id: int | None, *, budget_line_id: int) -> dict | None:
    """Проверить ссылку на заявку; вернуть её карточку или ``None`` без ссылки.

    Поднимает ``RequestLinkViolation`` с текстом, который читает финансист в
    409: какая заявка, что с ней не так и что делать.
    """
    if request_id is None:
        return None

    brief = approvals.get_request_brief(request_id)
    if brief is None:
        raise RequestLinkViolation(f"Заявка #{request_id} не найдена")
    if brief["status"] != APPROVED:
        raise RequestLinkViolation(
            f"Заявка {brief['code']} не одобрена (статус «{brief['status']}») — "
            f"договор или счёт заводятся только по одобренной заявке"
        )
    if brief["budget_line_id"] is None:
        raise RequestLinkViolation(
            f"В заявке {brief['code']} не указана строка бюджета — связать её "
            f"с документом договорного контура нельзя"
        )
    if brief["budget_line_id"] != budget_line_id:
        raise RequestLinkViolation(
            f"Заявка {brief['code']} одобрена по другой строке бюджета "
            f"(#{brief['budget_line_id']}) — документ по заявке заключается на "
            f"ту же строку"
        )
    return brief


def log_link(request_id: int | None, *, kind: str, document_id: int,
             title: str, url: str, actor_id: int | None) -> None:
    """След в ленте заявки: «по заявке заведён документ …»."""
    if request_id is None:
        return
    approvals.log_linked_document(
        request_id, kind=kind, document_id=document_id,
        title=title, url=url, actor_id=actor_id,
    )
