"""Счета на оплату без договора — второй канал расхода бюджета.

Устройство параллельно ``agreement_service``: счёт ссылается на ОДНУ строку
бюджета, на контрагента-поставщика, несёт сумму и скан. Отличия — в
докстринге модели ``Invoice``; для сервиса важны два:

- **валюта не приходит извне** — она снимается со строки бюджета при
  создании (``line.budget.currency``), поэтому сверять валюту, как это делает
  договор, здесь нечего;
- **лимит бюджета НЕ проверяется** — в первой фазе счёт не занимает бюджет
  (``budget_calc`` считает занятость только по договорам). Отсюда и
  отсутствие ``SELECT … FOR UPDATE`` на строке: блокировать нечего, пока
  никакой остаток от счёта не зависит. Когда счёт начнут учитывать в остатке,
  сюда вернутся и блокировка строки, и ``check_capacity`` — ровно тем же
  приёмом, что в ``agreement_service`` (см. докстринг модели ``Invoice``).

Статус и согласование при этом читаются с самого счёта; из строки бюджета
берётся только контекст (администратор, программа, год) для карточки.
"""

from __future__ import annotations

import logging

from django.db import transaction
from django.http import Http404

from apps.contracts.models import (
    Budget,
    BudgetLine,
    BudgetStatus,
    Counterparty,
    CounterpartyStatus,
    Invoice,
    InvoiceStatus,
)
from apps.contracts.services.counterparty_service import get_counterparty_or_404
from apps.contracts.services.reference_service import ReferenceConflict, conflict_as
# Единственные соседи, и только через interface — прямой импорт их
# models/services запрещён (apps/core/tests/test_app_isolation.py).
from apps.media_files import interface as media
from apps.signoff import interface as signoff

logger = logging.getLogger(__name__)


class InvoiceRuleViolation(Exception):
    """Счёт нарушает доменное правило (статус бюджета/контрагента, переход)."""


# Разрешённые переходы статуса счёта. Чего здесь нет — запрещено; ``paid`` и
# ``cancelled`` терминальны. Форма та же, что у ``agreement_service`` — счёт
# ведётся по ней и вручную (HTTP-путь), и колбэками движка, когда согласование
# счёта подключат.
ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    InvoiceStatus.DRAFT: frozenset({InvoiceStatus.ON_REVIEW,
                                    InvoiceStatus.CANCELLED}),
    InvoiceStatus.ON_REVIEW: frozenset({InvoiceStatus.APPROVED,
                                        InvoiceStatus.DRAFT,
                                        InvoiceStatus.CANCELLED}),
    # ``approved → draft`` — возврат согласованного счёта на доработку
    # (по образцу договора: ``signoff.engine.reopen``). Без него исправить
    # согласованный счёт можно было бы только заведя рядом второй.
    InvoiceStatus.APPROVED: frozenset({InvoiceStatus.PAID,
                                       InvoiceStatus.ON_REVIEW,
                                       InvoiceStatus.DRAFT,
                                       InvoiceStatus.CANCELLED}),
    InvoiceStatus.PAID: frozenset(),
    InvoiceStatus.CANCELLED: frozenset(),
}

_RELATED = ("budget_line", "budget_line__program", "budget_line__budget",
            "budget_line__budget__administrator",
            "budget_line__budget__administrator__country", "counterparty")


def _validate_context(line: BudgetLine, counterparty, *,
                      check_budget_status: bool = True,
                      check_counterparty_status: bool = True) -> None:
    """Проверки контекста счёта.

    Статусы бюджета и контрагента сверяются при СОЗДАНИИ и при смене
    соответствующей ссылки, но не при правке остальных полей уже
    существующего счёта — иначе заблокированный задним числом контрагент
    (или закрытый бюджет) запер бы даже исправление опечатки в наименовании.
    Та же логика, что в ``agreement_service._validate_context``.

    Согласование бюджета и контрагента проверяется только там, где для их
    типа заведён активный маршрут (``has_active_route``): без единого
    маршрута все записи ``approval_state = draft``, и безусловная проверка
    запретила бы выписывать счета вообще. Валюта здесь не проверяется — она
    не приходит извне, а снимается с бюджета в ``create_invoice``.
    """
    budget = line.budget
    if check_budget_status:
        if budget.status != BudgetStatus.ACTIVE:
            raise InvoiceRuleViolation(
                "Бюджет закрыт — счета к его строкам не выписываются")
        if (not budget.is_approved
                and signoff.has_active_route(Budget.SIGNOFF_SUBJECT_TYPE)):
            raise InvoiceRuleViolation(
                "Бюджет не согласован — деньги с него расходовать нельзя, "
                "отправьте его на согласование"
            )
    if check_counterparty_status:
        if counterparty.status != CounterpartyStatus.ACTIVE:
            raise InvoiceRuleViolation(
                f"Контрагент «{counterparty.name}» в статусе {counterparty.status} — "
                "счёт по нему выписать нельзя"
            )
        if (not counterparty.is_approved
                and signoff.has_active_route(Counterparty.SIGNOFF_SUBJECT_TYPE)):
            raise InvoiceRuleViolation(
                f"Контрагент «{counterparty.name}» не согласован — "
                "счёт по нему выписать нельзя"
            )


def _get_line_or_404(line_id: int) -> BudgetLine:
    """Строка бюджета с развёрнутым родителем — БЕЗ блокировки.

    Договор берёт строку ``SELECT … FOR UPDATE``, потому что проверяет и
    занимает остаток. Счёт остаток не трогает (см. докстринг модуля), поэтому
    ему достаточно снимка; ``select_related`` нужен, чтобы карточка собралась
    из закэшированных связей, а не запросом на каждое поле.
    """
    line = (BudgetLine.objects
            .select_related("program", "budget", "budget__administrator",
                            "budget__administrator__country")
            .filter(pk=line_id).first())
    if line is None:
        raise Http404("Строка бюджета не найдена")
    return line


def list_invoices(*, budget_id: int | None = None, budget_line_id: int | None = None,
                  counterparty_id: int | None = None,
                  administrator_id: int | None = None, program_id: int | None = None,
                  status: str | None = None, period_year: int | None = None):
    """``budget_id`` фильтрует по бюджету целиком, ``budget_line_id`` — по
    одной программе (как в ``list_agreements``)."""
    query = Invoice.objects.select_related(*_RELATED)
    if budget_id is not None:
        query = query.filter(budget_line__budget_id=budget_id)
    if budget_line_id is not None:
        query = query.filter(budget_line_id=budget_line_id)
    if counterparty_id is not None:
        query = query.filter(counterparty_id=counterparty_id)
    if administrator_id is not None:
        query = query.filter(budget_line__budget__administrator_id=administrator_id)
    if program_id is not None:
        query = query.filter(budget_line__program_id=program_id)
    if status is not None:
        query = query.filter(status=status)
    if period_year is not None:
        query = query.filter(budget_line__budget__period_year=period_year)
    return list(query)


def get_invoice_or_404(invoice_id: int) -> Invoice:
    row = Invoice.objects.select_related(*_RELATED).filter(pk=invoice_id).first()
    if row is None:
        raise Http404("Счёт не найден")
    return row


def serialize_invoice(invoice: Invoice) -> dict:
    line = invoice.budget_line
    budget = line.budget
    return {
        "id": invoice.pk,
        "name": invoice.name,
        "note": invoice.note,
        "budget_line_id": invoice.budget_line_id,
        # Родительский бюджет — рядом со строкой: карточка ссылается на него,
        # а не на безымянную строку (как у договора).
        "budget_id": budget.pk,
        # Администратор и программа — развёрнуто, хотя на счёте их колонок нет:
        # читаются через строку бюджета, разойтись с ней не могут.
        "administrator_id": budget.administrator_id,
        "administrator_name": budget.administrator.display_name,
        "program_id": line.program_id,
        "program_name": line.program.display_name,
        "expense_item": line.program.expense_item,
        "period_year": budget.period_year,
        "counterparty_id": invoice.counterparty_id,
        "counterparty_name": invoice.counterparty.name,
        "counterparty_bin_iin": invoice.counterparty.bin_iin,
        "amount": invoice.amount,
        "currency": invoice.currency,
        "file_id": invoice.file_id,
        "status": invoice.status,
        "approval_state": invoice.approval_state,
        "created_by": invoice.created_by,
        "created_at": invoice.created_at,
        "updated_at": invoice.updated_at,
    }


@transaction.atomic
def create_invoice(*, name: str, budget_line_id: int, counterparty_id: int,
                   amount, note: str = "", status: str | None = None,
                   created_by: int | None = None) -> Invoice:
    line = _get_line_or_404(budget_line_id)
    counterparty = get_counterparty_or_404(counterparty_id)
    _validate_context(line, counterparty)

    status = status or InvoiceStatus.DRAFT
    if status not in InvoiceStatus.values:
        raise InvoiceRuleViolation(f"Неизвестный статус счёта: {status}")

    # Валюта — со строки бюджета, а не из тела запроса: счёт выписывается в
    # валюте того бюджета, из которого его оплачивают (см. докстринг модели).
    return Invoice.objects.create(
        name=name, note=note, budget_line=line, counterparty=counterparty,
        amount=amount, currency=line.budget.currency,
        status=status, created_by=created_by,
    )


@transaction.atomic
def update_invoice(invoice_id: int, **fields) -> Invoice:
    """Правка счёта. Статус здесь НЕ принимается — для него ``change_status``
    с проверкой перехода (иначе PATCH обходил бы ``ALLOWED_TRANSITIONS``).

    Валюта не правится: она привязана к бюджету строки. Смена строки на строку
    другого бюджета переносит счёт в другую валюту — это отдельное действие
    (меняется ``budget_line_id``), и валюта пересчитывается со строки, а не
    задаётся полем.
    """
    invoice = get_invoice_or_404(invoice_id)
    invoice.assert_editable()

    line_id = fields.get("budget_line_id") or invoice.budget_line_id
    budget_changed = line_id != invoice.budget_line_id
    line = _get_line_or_404(line_id)

    counterparty_id = fields.get("counterparty_id") or invoice.counterparty_id
    counterparty_changed = counterparty_id != invoice.counterparty_id
    counterparty = get_counterparty_or_404(counterparty_id)

    _validate_context(line, counterparty,
                      check_budget_status=budget_changed,
                      check_counterparty_status=counterparty_changed)

    changed = [key for key, value in fields.items() if value is not None]
    for key in changed:
        setattr(invoice, key, fields[key])
    # Смена строки может увести счёт в бюджет другой валюты — снимаем её
    # заново, чтобы колонка не осталась от прежнего бюджета.
    if budget_changed:
        invoice.budget_line = line
        invoice.counterparty = counterparty
        invoice.currency = line.budget.currency
    if changed or budget_changed:
        invoice.save()
    return get_invoice_or_404(invoice.pk)


@transaction.atomic
def submit_for_approval(invoice_id: int, *, actor_id: int | None = None) -> dict:
    """Отправить счёт на согласование. Возвращает карточку процесса.

    Штатный путь отправки — предметные проверки проходят ДО запуска процесса,
    как у договора (``agreement_service.submit_for_approval``). Отличий от
    договора два, и оба — из устройства счёта:

    * лимит бюджета не проверяется и строка НЕ блокируется: счёт бюджет не
      занимает (см. докстринг модуля), блокировать нечего, и ни
      ``check_capacity``, ни ``SELECT … FOR UPDATE`` здесь нет;
    * скан обязателен уже на отправке. Счёт без договора и ЕСТЬ тот документ,
      по которому платят, — согласующему без него нечего смотреть. Ту же
      проверку продублирует ``change_status`` при переходе в ``on_review``
      (его делает колбэк ``on_started``), но упереться в неё там значило бы
      получить отказ из середины транзакции движка. Проверяем здесь, где
      сообщение адресно; это ровно то место, которое предсказывал докстринг
      ``change_status``.

    Статусы бюджета и контрагента сверяются полностью: к моменту отправки
    заблокированный контрагент или закрытый бюджет — причина не выпускать
    счёт на согласование, в отличие от правки отдельного поля черновика
    (``_validate_context`` с обоими флагами, как у ``create_invoice``).
    """
    invoice = get_invoice_or_404(invoice_id)
    if invoice.status != InvoiceStatus.DRAFT:
        raise InvoiceRuleViolation(
            f"На согласование отправляется черновик; счёт в статусе "
            f"«{invoice.get_status_display()}»"
        )
    if not invoice.file_id:
        raise InvoiceRuleViolation(
            "К счёту не приложен скан счёта на оплату — загрузите его, "
            "прежде чем отправлять на согласование"
        )

    line = _get_line_or_404(invoice.budget_line_id)
    _validate_context(line, invoice.counterparty)

    # enrich=True: карточка уходит прямо в HTTP-ответ, и фронтенду после
    # отправки нужно показать «кто согласует», а не голые user_id.
    return signoff.start_process(subject_type=Invoice.SIGNOFF_SUBJECT_TYPE,
                                 subject_id=invoice.pk, initiator_id=actor_id,
                                 enrich=True)


def _assert_not_pending_approval(invoice: Invoice) -> None:
    """Пока по счёту идёт согласование, статус ведёт решение согласующих, а
    не ручной перевод. Дословно как ``agreement_service._assert_not_pending_approval``:
    заперт ровно ``pending``, escape-hatch — выключенный signoff.

    В первой фазе счёт согласуемым типом не зарегистрирован, маршрута нет и
    ``approval_state`` не выходит из ``draft`` — проверка инертна. Она стоит
    здесь заранее, чтобы подключение согласования счёта не потребовало
    переписывать смену статуса.
    """
    if invoice.approval_state != signoff.ApprovalState.PENDING:
        return
    from apps.core.services import service_enabled

    if not service_enabled("signoff"):
        return
    raise InvoiceRuleViolation(
        f"Счёт «{invoice.name}» на согласовании — дождитесь решения или "
        "отзовите согласование; статус сейчас ведёт оно, а не ручной перевод"
    )


@transaction.atomic
def change_status(invoice_id: int, new_status: str, *, actor_id: int | None = None,
                  enforce_approval_lock: bool = False) -> Invoice:
    """Сдвинуть счёт по ``ALLOWED_TRANSITIONS``.

    ``enforce_approval_lock`` ставит HTTP-путь: под идущим согласованием
    ручной перевод запрещён. Проверки лимита при смене статуса нет — счёт
    бюджет не занимает (см. докстринг модуля)."""
    invoice = get_invoice_or_404(invoice_id)
    if enforce_approval_lock:
        _assert_not_pending_approval(invoice)
    current = invoice.status

    if new_status not in InvoiceStatus.values:
        raise InvoiceRuleViolation(f"Неизвестный статус счёта: {new_status}")
    if new_status == current:
        return invoice
    if new_status not in ALLOWED_TRANSITIONS[current]:
        raise InvoiceRuleViolation(
            f"Переход «{InvoiceStatus(current).label}» → "
            f"«{InvoiceStatus(new_status).label}» не разрешён"
        )

    # Счёт без договора и ЕСТЬ тот документ, по которому платят: провести его
    # дальше черновика без приложенного скана нельзя. Проверяется на каждом
    # шаге вперёд, а не только на выходе из черновика, — чтобы инвариант «всё,
    # что не черновик, имеет скан» держался и если файл когда-нибудь окажется
    # снят. Отмена — исключение: отменяемому счёту скан уже не нужен, и
    # требовать его значило бы запереть черновик, к которому его так и не
    # приложили. Это же место станет проверкой перед отправкой на
    # согласование, когда её подключат (скан нужен согласующему).
    if new_status not in (InvoiceStatus.DRAFT, InvoiceStatus.CANCELLED) and not invoice.file_id:
        raise InvoiceRuleViolation(
            "К счёту не приложен скан счёта на оплату — загрузите его, "
            "прежде чем менять статус"
        )

    invoice.status = new_status
    invoice.save(update_fields=["status", "updated_at"])
    logger.info("invoice %s: %s -> %s by user=%s",
                invoice.pk, current, new_status, actor_id)
    return invoice


def attach_file(invoice_id: int, *, data: bytes, filename: str, mime: str,
                owner_id: int | None = None) -> Invoice:
    """Положить скан счёта в media_files и запомнить его id.

    Тот же пайплайн и scope ``generic``, что у скана договора
    (``agreement_service.attach_file``): приватный, без ограничения по mime.
    Повторная загрузка ЗАМЕЩАЕТ ссылку; старый файл в хранилище остаётся —
    тихая потеря приложенного счёта хуже лишнего объекта в S3.
    """
    invoice = get_invoice_or_404(invoice_id)
    stored = media.store_file(data=data, filename=filename, mime=mime,
                              scope="generic", owner_id=owner_id)
    invoice.file_id = str(stored["id"])
    invoice.save(update_fields=["file_id", "updated_at"])
    return invoice


def file_url(invoice: Invoice) -> str | None:
    """Ссылка на скан счёта (подписанная — scope ``generic`` приватный)."""
    if not invoice.file_id:
        return None
    return media.get_file_url(invoice.file_id)


@transaction.atomic
def delete_invoice(invoice_id: int) -> None:
    """Удаление счёта — только черновик.

    Счёт, который уже уходил на согласование или был оплачён, — часть истории
    бюджета; его отменяют (``status=cancelled``), а не стирают.
    """
    invoice = get_invoice_or_404(invoice_id)
    invoice.assert_editable()
    if invoice.status != InvoiceStatus.DRAFT:
        raise ReferenceConflict(
            "Удалить можно только черновик — остальные счета отменяются "
            "(status=cancelled)"
        )
    invoice.delete()
