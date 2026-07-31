"""Договоры — единственная транзакционная сущность модуля.

Здесь живут все проверки, из-за которых договор нельзя просто записать в
таблицу: валюта должна совпадать с бюджетом, бюджет и контрагент должны быть
живыми, сумма должна помещаться в остаток СТРОКИ, а статус — меняться только
по разрешённым переходам.

Договор ссылается на ``BudgetLine``, а не на ``Budget``: деньги выделены
программе. Статус, валюта и состояние согласования при этом читаются с
родительского бюджета — у строки своих нет.
"""

from __future__ import annotations

import logging

from django.db import transaction
from django.http import Http404

from apps.contracts.models import (
    Agreement,
    AgreementStatus,
    Budget,
    BudgetLine,
    BudgetStatus,
    Counterparty,
    CounterpartyStatus,
)
from apps.contracts.services import budget_calc
from apps.contracts.services.counterparty_service import get_counterparty_or_404
from apps.contracts.services.reference_service import ReferenceConflict, conflict_as
# Единственный сосед, к которому обращается этот модуль, и только через его
# interface — прямой импорт apps.media_files.models/services запрещён
# (apps/core/tests/test_app_isolation.py).
from apps.media_files import interface as media
from apps.signoff import interface as signoff

logger = logging.getLogger(__name__)


class AgreementRuleViolation(Exception):
    """Договор нарушает доменное правило (валюта, статус, состояние справочника)."""


# Разрешённые переходы статуса. Чего здесь нет — то запрещено; «исполнен» и
# «расторгнут» терминальны.
#
# Таблица осталась за этой аппкой и после подключения ``apps.signoff``:
# движок согласования знает только «согласовано / отклонено», а какой статус
# договора этому соответствует и разрешён ли такой переход — вопрос предметный.
# Переводит договор по ней ``approval_hooks``, вызываемый движком из его
# транзакции.
ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    AgreementStatus.DRAFT: frozenset({AgreementStatus.ON_REVIEW,
                                      AgreementStatus.TERMINATED}),
    AgreementStatus.ON_REVIEW: frozenset({AgreementStatus.APPROVED,
                                          AgreementStatus.DRAFT,
                                          AgreementStatus.TERMINATED}),
    # ``approved → draft`` — это возврат на доработку СОГЛАСОВАННОГО договора
    # (``approval_hooks._agreement_on_rework``, ``signoff.engine.reopen``).
    # Без него единственным способом исправить опечатку в согласованном
    # договоре было бы завести рядом второй.
    AgreementStatus.APPROVED: frozenset({AgreementStatus.SIGNED,
                                         AgreementStatus.ON_REVIEW,
                                         AgreementStatus.DRAFT,
                                         AgreementStatus.TERMINATED}),
    AgreementStatus.SIGNED: frozenset({AgreementStatus.EXECUTED,
                                       AgreementStatus.TERMINATED}),
    AgreementStatus.EXECUTED: frozenset(),
    AgreementStatus.TERMINATED: frozenset(),
}


def _lock_line(line_id: int) -> BudgetLine:
    """Взять строку бюджета с ``SELECT … FOR UPDATE``.

    Обязательно для любой операции, которая проверяет остаток и потом на
    него опирается: без блокировки два одновременных договора на 600 000 ₸
    оба увидят остаток 1 000 000 ₸, оба пройдут проверку и вместе выйдут за
    лимит. Читающие пути (список, карточка) блокировку не берут — им
    достаточно снимка.

    Блокируется именно СТРОКА: лимит проверяется по ней, и блокировать весь
    бюджет значило бы сериализовать оформление договоров по не связанным
    между собой программам.

    ``select_related`` по родителю обязателен — из бюджета читаются валюта,
    статус и состояние согласования, и без него каждая проверка стоила бы
    лишнего запроса. На саму блокировку он не влияет: ``of=("self",)``
    держит замок на строке, не пытаясь заблокировать ещё и присоединённые
    таблицы (в Postgres ``FOR UPDATE`` иначе распространился бы на них).

    Вызывается только внутри ``transaction.atomic()`` — вне транзакции
    ``select_for_update()`` в Django поднимает ``TransactionManagementError``.
    """
    line = (BudgetLine.objects.select_for_update(of=("self",))
            .select_related("program", "budget", "budget__administrator",
                            "budget__administrator__country")
            .filter(pk=line_id).first())
    if line is None:
        raise Http404("Строка бюджета не найдена")
    return line


def approval_required_for(subject_type: str) -> bool:
    """Действует ли гейт согласования для этого типа объектов.

    Проверка «объект согласован?» включается ТОЛЬКО там, где заведён активный
    маршрут. Иначе установка без единого настроенного маршрута сломалась бы
    целиком: все существующие бюджеты и контрагенты имеют
    ``approval_state = draft``, и безусловная проверка запретила бы заводить
    договоры вообще — при том что согласование никто не включал.

    Обратная сторона осознанная: заведение маршрута на бюджеты — действие с
    последствиями, после него несогласованные строки перестают быть
    источником денег. Это и есть смысл включения согласования.
    """
    return signoff.has_active_route(subject_type)


def _validate_context(line: BudgetLine, counterparty, currency: str, *,
                      check_budget_status: bool = True,
                      check_counterparty_status: bool = True) -> None:
    """Проверки контекста договора.

    Статусы бюджета и контрагента проверяются при СОЗДАНИИ договора и при
    смене соответствующей ссылки — но не при правке уже существующего
    договора, у которого эта ссылка не менялась. Иначе заблокированный
    задним числом контрагент (или закрытый бюджет) запирал бы договор
    целиком: нельзя было бы исправить даже опечатку в названии, а
    ровно в такой ситуации правки и требуются чаще всего.

    Согласование бюджета и контрагента проверяется ТАМ ЖЕ и по той же
    причине: несогласованный бюджет не должен становиться источником денег,
    но и отозванное задним числом согласование не должно запирать правку
    названия у давно заключённого договора.

    Валюта проверяется всегда: она обязана совпадать с бюджетом в любой
    момент, иначе «остаток» станет суммой разных валют.
    """
    budget = line.budget
    if check_budget_status:
        if budget.status != BudgetStatus.ACTIVE:
            raise AgreementRuleViolation(
                "Бюджет закрыт — новые договоры к его строкам не привязываются")
        if (not budget.is_approved
                and approval_required_for(Budget.SIGNOFF_SUBJECT_TYPE)):
            raise AgreementRuleViolation(
                "Бюджет не согласован — деньги с него расходовать нельзя, "
                "отправьте его на согласование"
            )
    if check_counterparty_status:
        if counterparty.status != CounterpartyStatus.ACTIVE:
            raise AgreementRuleViolation(
                f"Контрагент «{counterparty.name}» в статусе {counterparty.status} — "
                "договор с ним заключить нельзя"
            )
        if (not counterparty.is_approved
                and approval_required_for(Counterparty.SIGNOFF_SUBJECT_TYPE)):
            raise AgreementRuleViolation(
                f"Контрагент «{counterparty.name}» не согласован — "
                "договор с ним заключить нельзя"
            )
    if currency != budget.currency:
        # Конвертации в первой фазе нет: договор в USD, списанный с бюджета
        # в KZT, сделал бы «остаток» суммой разных валют — числом, которое
        # ничего не значит.
        raise AgreementRuleViolation(
            f"Валюта договора ({currency}) не совпадает с валютой бюджета "
            f"({budget.currency})"
        )


def list_agreements(*, budget_id: int | None = None, budget_line_id: int | None = None,
                    counterparty_id: int | None = None,
                    administrator_id: int | None = None, program_id: int | None = None,
                    status: str | None = None, period_year: int | None = None):
    """``budget_id`` фильтрует по бюджету ЦЕЛИКОМ (все его программы),
    ``budget_line_id`` — по одной программе. Нужны оба: карточка бюджета
    показывает договоры всех своих строк, карточка строки — только свои."""
    query = Agreement.objects.select_related(
        "budget_line", "budget_line__program", "budget_line__budget",
        "budget_line__budget__administrator",
        "budget_line__budget__administrator__country", "counterparty",
    )
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


def get_agreement_or_404(agreement_id: int) -> Agreement:
    row = (Agreement.objects
           .select_related("budget_line", "budget_line__program", "budget_line__budget",
        "budget_line__budget__administrator",
        "budget_line__budget__administrator__country", "counterparty",
                           )
           .filter(pk=agreement_id).first())
    if row is None:
        raise Http404("Договор не найден")
    return row


def serialize_agreement(agreement: Agreement) -> dict:
    line = agreement.budget_line
    budget = line.budget
    return {
        "id": agreement.pk,
        "number": agreement.number,
        "name": agreement.name,
        "budget_line_id": agreement.budget_line_id,
        # Родительский бюджет отдаётся рядом со строкой: карточка договора
        # ссылается именно на него («Бюджет 2026 проекта А»), а не на
        # безымянную строку.
        "budget_id": budget.pk,
        # Администратор и программа отдаются РАЗВЁРНУТО, хотя в БД их нет на
        # договоре: спецификация показывает их как поля договора, и фронтенд
        # рисует их в списке. Читаются они всегда через строку бюджета, так
        # что разойтись с ней не могут.
        "administrator_id": budget.administrator_id,
        "administrator_name": budget.administrator.display_name,
        "program_id": line.program_id,
        "program_name": line.program.display_name,
        "expense_item": line.program.expense_item,
        "period_year": budget.period_year,
        "counterparty_id": agreement.counterparty_id,
        "counterparty_name": agreement.counterparty.name,
        "counterparty_bin_iin": agreement.counterparty.bin_iin,
        "payment_type": agreement.payment_type,
        "amount": agreement.amount,
        "currency": agreement.currency,
        "file_id": agreement.file_id,
        "signed_date": agreement.signed_date,
        "status": agreement.status,
        "approval_state": agreement.approval_state,
        "created_by": agreement.created_by,
        "created_at": agreement.created_at,
        "updated_at": agreement.updated_at,
    }


@transaction.atomic
def create_agreement(*, number: str, name: str, budget_line_id: int,
                     counterparty_id: int,
                     amount, payment_type: str, currency: str = "KZT",
                     signed_date=None, status: str | None = None,
                     created_by: int | None = None) -> Agreement:
    line = _lock_line(budget_line_id)
    counterparty = get_counterparty_or_404(counterparty_id)
    _validate_context(line, counterparty, currency)

    status = status or AgreementStatus.DRAFT
    if status not in AgreementStatus.values:
        raise AgreementRuleViolation(f"Неизвестный статус договора: {status}")

    # Черновик лимит не проверяет — он его и не занимает
    # (budget_calc.COMMITTING_STATUSES).
    if status in budget_calc.COMMITTING_STATUSES:
        budget_calc.check_capacity(line, amount)

    with conflict_as(f"Договор с номером {number} уже зарегистрирован"):
        return Agreement.objects.create(
            # Объектами, а не id: обе записи уже загружены проверками выше
            # (`_lock_line` тянет и бюджет с администратором и страной), и
            # ответ соберётся из закэшированных связей, а не новыми запросами.
            number=number, name=name, budget_line=line,
            counterparty=counterparty, amount=amount,
            payment_type=payment_type, currency=currency,
            signed_date=signed_date, status=status, created_by=created_by,
        )


@transaction.atomic
def update_agreement(agreement_id: int, **fields) -> Agreement:
    """Правка договора. Смена статуса здесь НЕ принимается — для неё есть
    ``change_status`` с проверкой перехода; иначе PATCH стал бы обходным
    путём мимо ``ALLOWED_TRANSITIONS``."""
    agreement = get_agreement_or_404(agreement_id)
    # Своя машина статусов запирает только терминальные состояния, а на
    # согласовании договор живёт в ``on_review`` — под неё он не попадает.
    agreement.assert_editable()
    if agreement.status in (AgreementStatus.EXECUTED, AgreementStatus.TERMINATED):
        raise AgreementRuleViolation(
            f"Договор в статусе «{agreement.get_status_display()}» не редактируется"
        )

    line_id = fields.get("budget_line_id") or agreement.budget_line_id
    budget_changed = line_id != agreement.budget_line_id
    line = _lock_line(line_id)

    counterparty_id = fields.get("counterparty_id") or agreement.counterparty_id
    counterparty_changed = counterparty_id != agreement.counterparty_id
    counterparty = get_counterparty_or_404(counterparty_id)

    amount = fields.get("amount") if fields.get("amount") is not None else agreement.amount
    currency = fields.get("currency") or agreement.currency
    _validate_context(line, counterparty, currency,
                      check_budget_status=budget_changed,
                      check_counterparty_status=counterparty_changed)

    if agreement.status in budget_calc.COMMITTING_STATUSES:
        # exclude_agreement_id — чтобы собственная СТАРАЯ сумма договора не
        # считалась чужой занятостью: без этого увеличение суммы на 1 ₸
        # сравнивалось бы с остатком, из которого уже вычтена вся старая
        # сумма, и почти всегда падало бы.
        budget_calc.check_capacity(line, amount, exclude_agreement_id=agreement.pk)

    changed = [key for key, value in fields.items() if value is not None]
    for key in changed:
        setattr(agreement, key, fields[key])
    if changed:
        with conflict_as("Договор с таким номером уже зарегистрирован"):
            agreement.save()
    return agreement


@transaction.atomic
def change_status(agreement_id: int, new_status: str, *, actor_id: int | None = None) -> Agreement:
    agreement = get_agreement_or_404(agreement_id)
    current = agreement.status

    if new_status not in AgreementStatus.values:
        raise AgreementRuleViolation(f"Неизвестный статус договора: {new_status}")
    if new_status == current:
        return agreement
    if new_status not in ALLOWED_TRANSITIONS[current]:
        raise AgreementRuleViolation(
            f"Переход «{AgreementStatus(current).label}» → "
            f"«{AgreementStatus(new_status).label}» не разрешён"
        )

    was_committing = current in budget_calc.COMMITTING_STATUSES
    will_commit = new_status in budget_calc.COMMITTING_STATUSES
    if will_commit and not was_committing:
        # Договор занимает бюджет только на этом переходе — здесь и
        # единственное место, где проверка лимита срабатывает при смене
        # статуса. Обратный переход (в черновик, в расторгнут) бюджет
        # освобождает и проверять нечего.
        line = _lock_line(agreement.budget_line_id)
        budget_calc.check_capacity(line, agreement.amount,
                                   exclude_agreement_id=agreement.pk)

    agreement.status = new_status
    agreement.save(update_fields=["status", "updated_at"])
    logger.info("agreement %s: %s -> %s by user=%s",
                agreement.number, current, new_status, actor_id)
    return agreement


@transaction.atomic
def submit_for_approval(agreement_id: int, *, actor_id: int | None = None) -> dict:
    """Отправить договор на согласование. Возвращает карточку процесса.

    Штатный путь отправки — в отличие от общего ``POST /api/signoff/v1/processes``,
    который принимает любой ``subject_id`` любого типа и потому админский.
    Здесь проверки предметные, и они обязаны пройти ДО запуска процесса:
    договор в статусе ``on_review`` уже занимает бюджет
    (``budget_calc.COMMITTING_STATUSES``), а именно в этот статус его
    переведёт ``approval_hooks._agreement_on_started``.

    Всё в одной транзакции с ``SELECT … FOR UPDATE`` на строке бюджета:
    иначе два договора, одновременно отправленные на согласование, оба
    увидели бы один и тот же остаток и вместе вышли бы за лимит.
    """
    agreement = get_agreement_or_404(agreement_id)
    if agreement.status != AgreementStatus.DRAFT:
        raise AgreementRuleViolation(
            f"На согласование отправляется черновик; договор в статусе "
            f"«{agreement.get_status_display()}»"
        )

    line = _lock_line(agreement.budget_line_id)
    _validate_context(line, agreement.counterparty, agreement.currency)
    budget_calc.check_capacity(line, agreement.amount,
                               exclude_agreement_id=agreement.pk)

    # enrich=True: карточка уходит прямо в HTTP-ответ, и фронтенду после
    # отправки нужно показать «кто согласует», а не голые user_id.
    return signoff.start_process(subject_type=Agreement.SIGNOFF_SUBJECT_TYPE,
                                 subject_id=agreement.pk, initiator_id=actor_id,
                                 enrich=True)


def attach_file(agreement_id: int, *, data: bytes, filename: str, mime: str,
                owner_id: int | None = None) -> Agreement:
    """Положить скан договора в media_files и запомнить его id.

    Собственного бакета модуль не заводит (инвариант №10, backend/README.md)
    — файл проходит ровно тот же пайплайн загрузки, что и HTTP-эндпоинт
    media. Scope ``generic``: приватный, без ограничения по mime (договор
    приходит и PDF-ом, и сканом), без вариантов-превью.

    Первая фаза — один файл на договор: повторная загрузка ЗАМЕЩАЕТ ссылку.
    Старый файл при этом остаётся в хранилище — удалять его отсюда нельзя,
    пока нет ясности, не ссылается ли на него что-то ещё, а тихая потеря
    подписанного договора хуже лишнего объекта в S3.
    """
    agreement = get_agreement_or_404(agreement_id)
    stored = media.store_file(data=data, filename=filename, mime=mime,
                              scope="generic", owner_id=owner_id)
    agreement.file_id = str(stored["id"])
    agreement.save(update_fields=["file_id", "updated_at"])
    return agreement


def file_url(agreement: Agreement) -> str | None:
    """Ссылка на скан договора (подписанная — scope ``generic`` приватный)."""
    if not agreement.file_id:
        return None
    return media.get_file_url(agreement.file_id)


@transaction.atomic
def delete_agreement(agreement_id: int) -> None:
    """Полное удаление договора.

    Разрешено только для черновиков: договор, который уже уходил на
    согласование, — часть истории бюджета, и его следует расторгать
    (``status=terminated``), а не стирать.
    """
    agreement = get_agreement_or_404(agreement_id)
    agreement.assert_editable()
    if agreement.status != AgreementStatus.DRAFT:
        raise ReferenceConflict(
            "Удалить можно только черновик — остальные договоры расторгаются "
            "(status=terminated)"
        )
    agreement.delete()
