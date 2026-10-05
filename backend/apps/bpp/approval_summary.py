"""Сводка документов модуля для решения из вышестоящей компании (B8.1).

Директора — в штате холдинга, а документы дочерних согласуются в их схемах.
Маршрут дочерней может разрешить решение прямо из очереди холдинга
(``ApprovalRoute.allow_direct_decisions``), и тогда карточка процесса в
холдинге показывает шапку документа (``describe``), ход согласования и эту
сводку: поля документа и таблицу его позиций (решение Руслана 02.10 —
«нужна и сводка позиций»). Значения — готовыми строками, суммы — через
``money.fmt``: signoff и фронт их не толкуют.

Прав читателя сводка не проверяет — signoff зовёт её только для владельца
задачи процесса (``signoff.registry.Summary``). Файлы и закрывающие
документы в неё не входят: их видно на адресе компании документа, куда
ведёт кнопка «Открыть в дочерней». Схема — компании документа (контекст
ставит signoff).
"""

from __future__ import annotations

from decimal import Decimal

from apps.bpp.models import (
    AccountableFundsRequest,
    AdvanceReport,
    Agreement,
    AgreementType,
    Invoice,
    InvoiceBasis,
    PurchaseRequest,
    PurchaseType,
)
from apps.bpp.services.counterparties import lookup as counterparty_lookup
from apps.bpp.services.money import fmt
from apps.project import interface as projects
from apps.refdata import interface as refdata

_DASH = "—"


def _field(label: str, value) -> dict:
    return {"label": label, "value": value if value not in (None, "") else _DASH}


def _column(key: str, label: str, align: str | None = None) -> dict:
    return {"key": key, "label": label, **({"align": align} if align else {})}


def _date(value) -> str:
    return value.strftime("%d.%m.%Y") if value else _DASH


def _qty(value) -> str:
    """Количество без хвостовых нулей: 10,000 → «10», 2,500 → «2,5»."""
    if value is None:
        return _DASH
    return format(Decimal(value).normalize(), "f").replace(".", ",")


def _yes(value: bool) -> str:
    return "Да" if value else "Нет"


def _project(project_id) -> str:
    brief = projects.project_brief([str(project_id)]).get(str(project_id)) or {}
    return " — ".join(part for part in (brief.get("code"), brief.get("name")) if part) or _DASH


def _article(article_id) -> str:
    if not article_id:
        return _DASH
    brief = refdata.article_brief([str(article_id)]).get(str(article_id)) or {}
    return " — ".join(part for part in (brief.get("code"), brief.get("name")) if part) or _DASH


def _counterparty(counterparty) -> str:
    return counterparty_lookup.display_name(counterparty) if counterparty is not None else _DASH


def _vat(with_vat: bool, rate, amount, currency: str) -> str:
    if not with_vat:
        return "Без НДС"
    if rate is None:
        return "С НДС"
    rate_text = format(Decimal(rate).normalize(), "f").replace(".", ",")
    return f"{rate_text} % — {fmt(amount, currency)}" if amount is not None else f"{rate_text} %"


def _uoms(items) -> dict[str, str]:
    ids = list({str(item.uom_id) for item in items})
    return {key: row.get("short_name") or row.get("code") or ""
            for key, row in (refdata.uom_brief(ids) if ids else {}).items()}


_ITEM_COLUMNS = [_column("request", "Заявка"), _column("name", "Позиция"),
                 _column("qty", "Кол-во", "right"), _column("uom", "Ед."),
                 _column("amount", "Сумма", "right")]


def _item_rows(lines, currency: str) -> list[dict]:
    """Строки счёта или договора — по позициям заявок, на которые они легли."""
    uoms = _uoms([line.request_item for line in lines])
    return [{"request": line.request_item.request.number,
             "name": line.request_item.name,
             "qty": _qty(line.qty),
             "uom": uoms.get(str(line.request_item.uom_id), ""),
             "amount": fmt(line.amount, currency) if line.amount is not None else _DASH}
            for line in lines]


def request_summary(request_id) -> dict | None:
    req = PurchaseRequest.objects.filter(pk=request_id).first()
    if req is None:
        return None
    items = list(req.items.order_by("line_no"))
    uoms = _uoms(items)
    currency = req.currency_code
    return {
        "fields": [
            _field("Проект", _project(req.project_id)),
            _field("Статья", _article(req.article_id)),
            _field("Вид закупки", dict(PurchaseType.choices).get(req.purchase_type)),
            _field("Нужно к", _date(req.need_date)),
            _field("Обоснование", req.justification),
            _field("Сумма", fmt(req.total_amount, currency)),
        ],
        "lines": {
            "columns": [_column("no", "№"), _column("name", "Наименование"),
                        _column("qty", "Кол-во", "right"), _column("uom", "Ед."),
                        _column("price", "Цена", "right"), _column("amount", "Сумма", "right"),
                        _column("need_date", "Нужно к")],
            "rows": [{"no": str(item.line_no),
                      "name": f"{item.name} — {item.specs}" if item.specs else item.name,
                      "qty": _qty(item.qty), "uom": uoms.get(str(item.uom_id), ""),
                      "price": fmt(item.price, currency), "amount": fmt(item.amount, currency),
                      "need_date": _date(item.need_date)} for item in items],
            "total": {"label": "Итого", "value": fmt(req.total_amount, currency)},
        },
    }


def invoice_summary(invoice_id) -> dict | None:
    inv = (Invoice.objects.select_related("counterparty", "agreement")
           .filter(pk=invoice_id).first())
    if inv is None:
        return None
    currency = inv.currency_code
    amount = fmt(inv.amount, currency)
    if currency != "KZT" and inv.amount_kzt is not None:
        amount = f"{amount} ({fmt(inv.amount_kzt, 'KZT')})"
    basis = dict(InvoiceBasis.choices).get(inv.basis, inv.basis)
    if inv.agreement_id:
        basis = f"{basis}: {inv.agreement.number}"
    ext = " от ".join(part for part in (inv.ext_number, _date(inv.ext_date) if inv.ext_date else "")
                      if part)
    lines = list(inv.lines.select_related("request_item", "request_item__request")
                 .order_by("request_item__request__number", "request_item__line_no"))
    return {
        "fields": [
            _field("Контрагент", _counterparty(inv.counterparty)),
            _field("Счёт контрагента", ext),
            _field("Проект", _project(inv.project_id)),
            _field("Статья", _article(inv.article_id)),
            _field("Основание", basis),
            _field("Аванс", _yes(inv.is_advance)),
            _field("Срок оплаты", _date(inv.due_date)),
            _field("НДС", _vat(inv.with_vat, inv.vat_rate, inv.vat_amount, currency)),
            _field("Сумма", amount),
        ],
        "lines": {"columns": _ITEM_COLUMNS, "rows": _item_rows(lines, currency),
                  "total": {"label": "Итого", "value": fmt(inv.amount, currency)}},
    }


def agreement_summary(agreement_id) -> dict | None:
    agr = (Agreement.objects.select_related("counterparty", "parent_agreement")
           .filter(pk=agreement_id).first())
    if agr is None:
        return None
    currency = agr.currency_code
    supplement = agr.parent_agreement_id is not None
    if agr.is_open:
        amount = "Открытый договор — без суммы"
    else:
        amount = fmt(agr.amount, currency) if agr.amount is not None else None
    fields = [
        _field("Вид", "Дополнительное соглашение" if supplement else "Договор"),
        _field("Контрагент", _counterparty(agr.counterparty)),
        _field("Наименование", agr.name),
        _field("Тип", dict(AgreementType.choices).get(agr.agreement_type)),
        _field("Прирост суммы" if supplement else "Сумма", amount),
        _field("НДС", _vat(agr.with_vat, agr.vat_rate, agr.vat_amount, currency)),
        _field("Действует до", _date(agr.valid_to)),
        _field("Проект", _project(agr.project_id)),
        _field("Статья", _article(agr.article_id)),
    ]
    if supplement:
        fields.insert(1, _field("Основной договор", agr.parent_agreement.number))
    lines = list(agr.items.select_related("request_item", "request_item__request")
                 .order_by("request_item__request__number", "request_item__line_no"))
    return {
        "fields": fields,
        "lines": {"columns": _ITEM_COLUMNS, "rows": _item_rows(lines, currency),
                  "total": ({"label": "Итого", "value": fmt(agr.amount, currency)}
                            if agr.amount is not None and not agr.is_open else None)},
    }


def accountable_summary(request_id) -> dict | None:
    req = AccountableFundsRequest.objects.filter(pk=request_id).first()
    if req is None:
        return None
    return {"fields": [
        _field("Проект", _project(req.project_id)),
        _field("Статья", _article(req.article_id)),
        _field("Сумма", fmt(req.amount, req.currency)),
        _field("Цель", req.goal),
    ], "lines": None}


def advance_report_summary(report_id) -> dict | None:
    report = AdvanceReport.objects.select_related("request").filter(pk=report_id).first()
    if report is None:
        return None
    return {"fields": [
        _field("Заявка на подотчёт", report.request.number),
        _field("Проект", _project(report.request.project_id)),
        _field("Трата", report.expense_name),
        _field("Сумма", fmt(report.amount, report.request.currency)),
    ], "lines": None}
