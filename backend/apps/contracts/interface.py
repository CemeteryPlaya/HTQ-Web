"""Публичный API аппки contracts для ДРУГИХ аппок.

Единственный способ, которым сосед имеет право обращаться к contracts.
Прямой импорт ``apps.contracts.models`` / ``apps.contracts.services`` из
другой аппки запрещён и ловится тестом
``apps/core/tests/test_app_isolation.py``.

Потребители — ``apps.approvals``: виджет ``budget_line_ref`` конструктора
форм хранит в запросе ``budget_line_id`` и через ``get_budget_lines_brief``
проверяет его при отправке и подписывает в таблице данных; и ``apps.tasks``:
партнёр хранит ``counterparty_id``, его привлечение — ``agreement_id``
(``get_counterparties_brief`` / ``get_agreements_brief``). Остальные
функции заведены не «на всякий случай», а потому
что вызовы просматриваются (отчётный раздел, которому нужен остаток бюджета).
Все следуют контракту, общему для всех ``interface.py`` в репозитории:

- ``require_service("contracts")`` первой строкой — если аппка выключена,
  вызывающий получает ``ServiceDisabled``, который ``api_view`` превращает в
  503-конверт, а не в голый 500;
- возвращаются простые ``dict``/``list``/``Decimal``, никогда ORM-объекты —
  сосед не должен получить возможность мутировать чужие строки.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Iterable

from apps.contracts.models import (
    Administrator,
    Agreement,
    Budget,
    BudgetLine,
    Counterparty,
    Country,
    Invoice,
    Program,
)
from apps.contracts.services import budget_calc
from apps.core.services import require_service


def get_budget_summary(budget_id: int) -> dict | None:
    """Бюджет ЦЕЛИКОМ: ``{id, administrator_name, period_year, currency,
    status, allocated, committed, remaining, lines: [...]}`` или ``None``,
    если бюджета нет.

    ``allocated`` — сумма строк: хранимого поля под неё нет
    (``budget_calc``). Строки отдаются простыми словарями — сосед не должен
    получить ORM-объект, который можно сохранить.
    """
    require_service("contracts")

    budget = (Budget.objects
              .select_related("administrator", "administrator__country")
              .prefetch_related("lines__program")
              .filter(pk=budget_id).first())
    if budget is None:
        return None

    lines = list(budget.lines.all())
    committed = budget_calc.committed_map([line.pk for line in lines])
    totals = budget_calc.totals_for_budget(lines, committed=committed)
    return {
        "id": budget.pk,
        "administrator_name": budget.administrator.display_name,
        "period_year": budget.period_year,
        "currency": budget.currency,
        "status": budget.status,
        "allocated": totals["allocated"],
        "committed": totals["committed"],
        "remaining": totals["remaining"],
        "lines": [
            {
                "id": line.pk,
                "program_name": line.program.display_name,
                "expense_item": line.program.expense_item,
                "amount": line.amount,
                "committed": committed.get(line.pk, budget_calc.ZERO),
                "remaining": line.amount - committed.get(line.pk, budget_calc.ZERO),
            }
            for line in lines
        ],
    }


def get_budget_line_remaining(budget_line_id: int) -> Decimal | None:
    """Остаток одной СТРОКИ — для проверок вида «хватит ли денег».

    Спрашивать остаток бюджета целиком для такой проверки нельзя: лимит
    расходуется по программам, и свободные деньги у соседней программы не
    делают договор допустимым (см. ``budget_calc.check_capacity``).
    """
    require_service("contracts")

    line = BudgetLine.objects.filter(pk=budget_line_id).first()
    if line is None:
        return None
    return budget_calc.remaining_for(line)


def get_budget_lines_brief(line_ids: Iterable[int]) -> list[dict]:
    """Строки бюджета ПЛОСКО и батчем — для чужой формы, которая хранит
    ``budget_line_id`` и должна его проверить и подписать.

    Батч, а не одиночный вызов, по той же причине, что и
    ``users.get_users_brief``: сосед сначала собирает id со всей формы, потом
    спрашивает один раз — иначе строка на каждый виджет превращается в N+1
    через границу аппки. Отсутствующие id в ответ просто не попадают — сосед
    сам решает, ошибка это или нет (для проверки при отправке — ошибка).

    ``administrator_is_active`` и ``budget_status`` отдаются затем, чтобы
    сосед мог отбить снятого с учёта администратора и закрытый бюджет теми
    же правилами, что ``accountable_funds_request_service.create_request``.
    ``administrator_user_id`` — задел под «согласует администратор бюджета»;
    сегодня он почти нигде не заполнен (см. докстринг ``Administrator``).
    """
    require_service("contracts")

    ids = sorted({int(line_id) for line_id in line_ids if line_id is not None})
    if not ids:
        return []

    lines = (BudgetLine.objects
             .select_related("budget__administrator", "program")
             .filter(pk__in=ids))
    return [
        {
            "id": line.pk,
            "administrator_id": line.budget.administrator_id,
            "administrator_name": line.budget.administrator.display_name,
            "administrator_user_id": line.budget.administrator.user_id,
            "administrator_is_active": line.budget.administrator.is_active,
            "administrator_country_id": line.budget.administrator.country_id,
            "program_id": line.program_id,
            "program_name": line.program.display_name,
            "expense_item": line.program.expense_item,
            "period_year": line.budget.period_year,
            "currency": line.budget.currency,
            "budget_status": line.budget.status,
            "approval_state": line.budget.approval_state,
        }
        for line in lines
    ]


def list_administrators_brief() -> list[dict]:
    """Справочник администраторов бюджета — ``[{id, name, country_id,
    is_active}]`` — для условий маршрута соседа («если администратор — …»).

    Неактивные не отфильтрованы по той же причине, что в
    ``approval_hooks._program_options``: список служит и для проверки уже
    сохранённых условий, и спрятанная запись сделала бы их нередактируемыми.
    """
    require_service("contracts")
    return [{"id": row.pk, "name": row.display_name, "country_id": row.country_id,
             "is_active": row.is_active}
            for row in Administrator.objects.select_related("country")]


def list_programs_brief() -> list[dict]:
    """Справочник программ — ``[{id, name, expense_item, is_active}]``."""
    require_service("contracts")
    return [{"id": row.pk, "name": row.display_name,
             "expense_item": row.expense_item, "is_active": row.is_active}
            for row in Program.objects.all()]


def list_countries_brief() -> list[dict]:
    """Справочник стран — ``[{id, name}]``."""
    require_service("contracts")
    return [{"id": row.pk, "name": row.name} for row in Country.objects.all()]


def list_documents_for_request(request_id: int) -> list[dict]:
    """Документы, заведённые по заявке конструктора «Запросы»: договоры и
    счета без договора одним плоским списком (``kind`` различает).

    Для блока «Документы по заявке» на карточке заявки. Без файлов и
    служебных меток — ровно то, что нужно, чтобы показать строку и дать
    ссылку; полная карточка — по ``url`` в разделе договоров.
    """
    require_service("contracts")

    rows: list[dict] = []
    for agreement in (Agreement.objects.select_related("counterparty")
                      .filter(request_id=request_id).order_by("-created_at")):
        rows.append({
            "kind": "agreement",
            "id": agreement.pk,
            "title": f"Договор {agreement.number} — {agreement.name}",
            "counterparty_name": agreement.counterparty.name,
            "amount": agreement.amount,
            "currency": agreement.currency,
            "status": agreement.status,
            "approval_state": agreement.approval_state,
            "url": f"/contracts/agreements/{agreement.pk}",
            "created_at": agreement.created_at,
        })
    for invoice in (Invoice.objects.select_related("counterparty")
                    .filter(request_id=request_id).order_by("-created_at")):
        rows.append({
            "kind": "invoice",
            "id": invoice.pk,
            "title": f"Счёт: {invoice.name}",
            "counterparty_name": invoice.counterparty.name,
            "amount": invoice.amount,
            "currency": invoice.currency,
            "status": invoice.status,
            "approval_state": invoice.approval_state,
            "url": f"/contracts/invoices/{invoice.pk}",
            "created_at": invoice.created_at,
        })
    return rows


def get_agreement_brief(agreement_id: int) -> dict | None:
    """Минимальная карточка договора для чужого UI (список согласований,
    карточка заявки): без файла, без служебных меток."""
    require_service("contracts")

    agreement = (Agreement.objects
                 .select_related("counterparty", "budget_line")
                 .filter(pk=agreement_id).first())
    if agreement is None:
        return None

    return {
        "id": agreement.pk,
        "number": agreement.number,
        "name": agreement.name,
        "counterparty_name": agreement.counterparty.name,
        "counterparty_bin_iin": agreement.counterparty.bin_iin,
        "amount": agreement.amount,
        "currency": agreement.currency,
        "payment_type": agreement.payment_type,
        "status": agreement.status,
        "budget_line_id": agreement.budget_line_id,
        "budget_id": agreement.budget_line.budget_id,
        "signed_date": agreement.signed_date,
    }


def get_counterparties_brief(counterparty_ids: Iterable[int]) -> list[dict]:
    """Контрагенты ПЛОСКО и батчем — для партнёра из ``apps.tasks``, который
    хранит ``counterparty_id`` (та же организация в роли исполнителя).

    Контакты отдаются вместе с реквизитами: партнёр при связывании
    подтягивает их к себе, и без них ему пришлось бы ходить за ними в чужой
    HTTP. Батч и «отсутствующие id просто не попадают» — как у
    ``get_budget_lines_brief``: ошибка это или нет, решает сосед.
    """
    require_service("contracts")

    ids = sorted({int(cp_id) for cp_id in counterparty_ids if cp_id is not None})
    if not ids:
        return []
    return [
        {
            "id": row.pk,
            "name": row.name,
            "bin_iin": row.bin_iin,
            "status": row.status,
            "approval_state": row.approval_state,
            "contact_name": row.contact_name,
            "phone": row.phone,
            "email": row.email,
            "address": row.address,
        }
        for row in Counterparty.objects.filter(pk__in=ids)
    ]


def get_agreements_brief(agreement_ids: Iterable[int]) -> list[dict]:
    """Договоры ПЛОСКО и батчем — для привлечения партнёра в ``apps.tasks``.

    ``counterparty_id`` отдаётся затем, чтобы сосед проверил, что договор
    заключён именно с контрагентом его партнёра. Сумм и бюджета здесь нет:
    привлечению нужен номер и ссылка, а деньги — дело карточки договора.
    """
    require_service("contracts")

    ids = sorted({int(a_id) for a_id in agreement_ids if a_id is not None})
    if not ids:
        return []
    return [
        {
            "id": row.pk,
            "number": row.number,
            "name": row.name,
            "counterparty_id": row.counterparty_id,
            "status": row.status,
            "approval_state": row.approval_state,
            "signed_date": row.signed_date,
        }
        for row in Agreement.objects.filter(pk__in=ids)
    ]


def get_invoice_brief(invoice_id: int) -> dict | None:
    """Минимальная карточка счёта на оплату для чужого UI (список
    согласований, когда согласование счёта подключат): без файла, без
    служебных меток. Парная к ``get_agreement_brief``."""
    require_service("contracts")

    invoice = (Invoice.objects
               .select_related("counterparty", "budget_line")
               .filter(pk=invoice_id).first())
    if invoice is None:
        return None

    return {
        "id": invoice.pk,
        "name": invoice.name,
        "counterparty_name": invoice.counterparty.name,
        "counterparty_bin_iin": invoice.counterparty.bin_iin,
        "amount": invoice.amount,
        "currency": invoice.currency,
        "status": invoice.status,
        "budget_line_id": invoice.budget_line_id,
        "budget_id": invoice.budget_line.budget_id,
    }
