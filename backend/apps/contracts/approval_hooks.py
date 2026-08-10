"""Регистрация согласуемых типов contracts в ``apps.signoff``.

Зависимость направлена ОДНОСТОРОННЕ: contracts знает про signoff, signoff
про contracts не знает никогда. Движок не может импортировать
``apps.contracts.models`` (``apps/core/tests/test_app_isolation.py``), поэтому
аппка сама приходит и отдаёт ему три вещи на каждый тип: класс модели (чтобы
signoff мог вести своё поле ``approval_state``), колбэки доменных последствий
и ``describe`` — способ показать объект в чужом интерфейсе.

Вызывается из ``ContractsConfig.ready()``.

**Про колбэки.** Они выполняются ВНУТРИ транзакции движка (``engine._finish``),
то есть исключение отсюда откатывает и согласование. Это осознанно: если
договор не удалось перевести в «согласован», то и процесс не должен считаться
завершённым — иначе останется процесс со статусом «согласовано» над
договором-черновиком, и вывести систему из этого состояния будет нечем.

**Про то, чего здесь нет.** У бюджета и контрагента доменных последствий
согласования нет — ``approval_state`` ведёт сам signoff, а больше в этих
моделях менять нечего. Их ``status`` (``active``/``closed``,
``active``/``blocked``) — другая ось: это жизненный цикл записи, а не
результат согласования, и связывать их значило бы, что отклонённый бюджет
«закрывается», хотя его как раз собираются переделать и отправить снова.

**Про факты (``facts``/``fact_fields``).** По ним signoff выбирает ветку
маршрута («после проверки согласует тот, кто отвечает за эту страну»), сам
не зная, что такое страна: он лишь сравнивает скаляры, которые получил
отсюда. Два правила, из-за которых этот файл выглядит именно так:

* **Ключи названы по смыслу, а не по типу.** У договора стран ДВЕ —
  администратора бюджета и контрагента, — и они регулярно разные
  (казахстанский проект закупается у турецкого поставщика). Общий ключ
  ``country_id`` означал бы, что настраивающий маршрут выберет одну из них
  наугад и никогда об этом не узнает.

  Обратная сторона того же правила: ``program_id`` у договора БЕЗ уточняющей
  приставки — это утверждение, что программа у него ровно одна (договор
  ссылается на одну строку бюджета, а строка — на одну программу), а не
  недосмотр по образцу стран. Уточнять там нечего, и ``budget_program_id``
  ради симметрии с ними завёл бы ложную развилку.
* **``fact_fields`` — функция.** Справочники стран и программ пополняются
  без перезапуска, а редактор маршрута должен показывать сегодняшний список.
"""

from __future__ import annotations

import logging

from apps.signoff import interface as signoff

from .models import (
    AccountableFundsRequest,
    AccountableFundsRequestStatus,
    AdvancePayment,
    AdvancePaymentStatus,
    Agreement,
    AgreementStatus,
    Budget,
    Counterparty,
    CompletionAct,
    ContractPayment,
    Country,
    Invoice,
    InvoiceStatus,
    PaymentType,
    Program,
)
from .services import budget_calc

logger = logging.getLogger(__name__)


# ── Договор: единственный тип с доменным последствием ───────────────────

def _agreement_to(subject_id: int, status: str) -> None:
    """Сдвинуть договор по его собственной машине статусов.

    Идёт через ``change_status``, а не ``update(status=...)``: таблица
    ``ALLOWED_TRANSITIONS`` — единственный источник правды о допустимых
    переходах, и обходить её отсюда значило бы завести второй.

    Импорт локальный: ``agreement_service`` импортирует ``signoff.interface``
    ради ``start_process``, а этот модуль импортируется из ``ready()`` —
    импорт верхнего уровня замкнул бы цикл через сервис.
    """
    from .services import agreement_service as agr_svc

    agreement = Agreement.objects.filter(pk=subject_id).first()
    if agreement is None:
        # Объект удалили, пока шло согласование. Ронять транзакцию движка
        # нечем помочь — процесс всё равно надо закрыть.
        logger.warning("signoff: договор %s не найден, статус не менялся", subject_id)
        return
    if agreement.status == status:
        return
    agr_svc.change_status(subject_id, status)


def _agreement_on_started(subject_id: int) -> None:
    _agreement_to(subject_id, AgreementStatus.ON_REVIEW)


def _agreement_on_approved(subject_id: int) -> None:
    _agreement_to(subject_id, AgreementStatus.APPROVED)


def _agreement_on_rejected(subject_id: int) -> None:
    # Отказ возвращает договор в черновик, а не в терминальный статус:
    # отклонённый договор переделывают и отправляют снова, а «расторгнут»
    # — состояние, из которого выхода нет. Править его при этом нельзя,
    # пока согласующий не вернёт его на доработку: за это отвечает
    # ``approval_state``, а не ``status`` (см. докстринг модуля).
    _agreement_to(subject_id, AgreementStatus.DRAFT)


def _agreement_on_rework(subject_id: int) -> None:
    """Возврат на доработку — тот же черновик, что и отказ.

    Своя машина статусов договора о доработке не знает и знать не должна:
    «на доработке» — состояние СОГЛАСОВАНИЯ (``approval_state``), а
    ``status`` отвечает на другой вопрос — какой стадии жизни достиг сам
    договор. Заводить под доработку шестой статус значило бы держать две
    колонки об одном и том же и однажды получить договор, который «на
    доработке» по одной и «согласован» по другой.

    Приходит сюда договор из двух разных мест: ``on_review`` (согласующий
    вернул на ходу) и ``approved`` (вернули уже согласованный —
    ``engine.reopen``). Второй переход и добавлен в ``ALLOWED_TRANSITIONS``
    ради этого случая.
    """
    _agreement_to(subject_id, AgreementStatus.DRAFT)


def _agreement_on_cancelled(subject_id: int) -> None:
    _agreement_to(subject_id, AgreementStatus.DRAFT)


# ── Счёт: доменные последствия по образцу договора ──────────────────────

def _invoice_to(subject_id: int, status: str) -> None:
    """Сдвинуть счёт по его собственной машине статусов.

    Дословно как ``_agreement_to``, только для счёта: идёт через
    ``change_status`` (единственный источник правды о переходах), а не
    ``update(status=...)``. ``enforce_approval_lock`` НЕ ставится — колбэк
    двигает статус, пока ``approval_state`` ещё pending, и лок, стоящий на
    ручном HTTP-переводе, здесь блокировал бы само согласование.
    """
    from .services import invoice_service as inv_svc

    invoice = Invoice.objects.filter(pk=subject_id).first()
    if invoice is None:
        logger.warning("signoff: счёт %s не найден, статус не менялся", subject_id)
        return
    if invoice.status == status:
        return
    inv_svc.change_status(subject_id, status)


def _invoice_on_started(subject_id: int) -> None:
    _invoice_to(subject_id, InvoiceStatus.ON_REVIEW)


def _invoice_on_approved(subject_id: int) -> None:
    _invoice_to(subject_id, InvoiceStatus.APPROVED)


def _invoice_on_rejected(subject_id: int) -> None:
    # Отказ возвращает счёт в черновик, а не в терминальный ``cancelled``:
    # отклонённый счёт переделывают и отправляют снова. ``cancelled`` — это
    # отдельное решение «счёт не оплачиваем», а не результат согласования.
    # Править счёт при этом всё равно нельзя, пока согласующий не вернёт его
    # на доработку: за это отвечает ``approval_state``, а не ``status``.
    _invoice_to(subject_id, InvoiceStatus.DRAFT)


def _invoice_on_rework(subject_id: int) -> None:
    # Возврат на доработку — тот же черновик, что и отказ (см. договор:
    # ``status`` — это стадия жизни счёта, «на доработке» — состояние
    # СОГЛАСОВАНИЯ, и держит его ``approval_state``). Приходит сюда счёт из
    # ``on_review`` (вернули на ходу) и из ``approved`` (вернули уже
    # согласованный — ``engine.reopen``); оба перехода в ``draft`` есть в
    # ``ALLOWED_TRANSITIONS``.
    _invoice_to(subject_id, InvoiceStatus.DRAFT)


def _invoice_on_cancelled(subject_id: int) -> None:
    _invoice_to(subject_id, InvoiceStatus.DRAFT)


# ── Предоплата: согласование отдельно от закрытия бухгалтерией ─────────

def _advance_payment_to(subject_id: int, status: str) -> None:
    from .services import advance_payment_service as payment_svc

    payment = AdvancePayment.objects.filter(pk=subject_id).first()
    if payment is None:
        logger.warning("signoff: предоплата %s не найдена, статус не менялся", subject_id)
        return
    if payment.status == status:
        return
    payment_svc.change_status(subject_id, status)


def _advance_payment_on_started(subject_id: int) -> None:
    _advance_payment_to(subject_id, AdvancePaymentStatus.ON_REVIEW)


def _advance_payment_on_approved(subject_id: int) -> None:
    _advance_payment_to(subject_id, AdvancePaymentStatus.AWAITING_ACCOUNTING)


def _advance_payment_on_rejected(subject_id: int) -> None:
    _advance_payment_to(subject_id, AdvancePaymentStatus.DRAFT)


def _advance_payment_on_rework(subject_id: int) -> None:
    _advance_payment_to(subject_id, AdvancePaymentStatus.DRAFT)


def _advance_payment_on_cancelled(subject_id: int) -> None:
    _advance_payment_to(subject_id, AdvancePaymentStatus.DRAFT)


def _describe_invoice(subject_id: int) -> dict | None:
    invoice = (Invoice.objects.select_related("counterparty")
               .filter(pk=subject_id).first())
    if invoice is None:
        return None
    return {
        # Номера у счёта нет (см. докстринг модели) — опознаётся
        # наименованием, поставщиком и суммой, тем же набором, что и __str__.
        "title": (f"Счёт: {invoice.name} "
                  f"({invoice.counterparty.name}, {invoice.amount} "
                  f"{invoice.currency})"),
        "url": f"/contracts/invoices/{invoice.pk}",
    }


def _describe_advance_payment(subject_id: int) -> dict | None:
    payment = (AdvancePayment.objects.select_related("agreement", "agreement__counterparty")
               .filter(pk=subject_id).first())
    if payment is None:
        return None
    return {
        "title": (f"Предоплата по договору {payment.agreement.number} "
                  f"({payment.agreement.counterparty.name}, {payment.amount} "
                  f"{payment.agreement.currency})"),
        "url": f"/contracts/advance-payments/{payment.pk}",
    }


def _advance_payment_facts(subject_id: int) -> dict:
    payment = (AdvancePayment.objects
               .select_related("agreement__budget_line__budget__administrator",
                               "agreement__counterparty")
               .filter(pk=subject_id).first())
    if payment is None:
        return {}
    agreement = payment.agreement
    return {
        "admin_country_id": agreement.budget_line.budget.administrator.country_id,
        "counterparty_country_id": agreement.counterparty.country_id,
        "program_id": agreement.budget_line.program_id,
        "amount": payment.amount,
        "currency": agreement.currency,
    }


def _advance_payment_fact_fields() -> list[dict]:
    countries = _country_options()
    return [
        {"key": "admin_country_id", "label": "Страна администратора бюджета",
         "type": "choice", "options": countries},
        {"key": "counterparty_country_id", "label": "Страна контрагента",
         "type": "choice", "options": countries},
        {"key": "program_id", "label": "Программа",
         "type": "choice", "options": _program_options()},
        {"key": "amount", "label": "Сумма предоплаты", "type": "number"},
        {"key": "currency", "label": "Валюта", "type": "string"},
    ]


def _contract_payment_to(subject_id: int, status: str) -> None:
    from .services import contract_payment_service as payment_svc

    payment = ContractPayment.objects.filter(pk=subject_id).first()
    if payment is not None and payment.status != status:
        payment_svc.change_status(subject_id, status)


def _contract_payment_on_started(subject_id: int) -> None:
    _contract_payment_to(subject_id, AdvancePaymentStatus.ON_REVIEW)


def _contract_payment_on_approved(subject_id: int) -> None:
    _contract_payment_to(subject_id, AdvancePaymentStatus.AWAITING_ACCOUNTING)


def _contract_payment_on_rejected(subject_id: int) -> None:
    _contract_payment_to(subject_id, AdvancePaymentStatus.DRAFT)


def _contract_payment_on_rework(subject_id: int) -> None:
    _contract_payment_to(subject_id, AdvancePaymentStatus.DRAFT)


def _contract_payment_on_cancelled(subject_id: int) -> None:
    _contract_payment_to(subject_id, AdvancePaymentStatus.DRAFT)


def _describe_contract_payment(subject_id: int) -> dict | None:
    payment = (ContractPayment.objects.select_related("agreement", "agreement__counterparty")
               .filter(pk=subject_id).first())
    if payment is None:
        return None
    return {
        "title": f"Оплата по договору {payment.agreement.number} ({payment.amount} {payment.agreement.currency})",
        "url": f"/contracts/contract-payments/{payment.pk}",
    }


def _contract_payment_facts(subject_id: int) -> dict:
    payment = (ContractPayment.objects
               .select_related("agreement__budget_line__budget__administrator", "agreement__counterparty")
               .filter(pk=subject_id).first())
    if payment is None:
        return {}
    agreement = payment.agreement
    return {
        "admin_country_id": agreement.budget_line.budget.administrator.country_id,
        "counterparty_country_id": agreement.counterparty.country_id,
        "program_id": agreement.budget_line.program_id,
        "amount": payment.amount,
        "currency": agreement.currency,
    }


def _contract_payment_fact_fields() -> list[dict]:
    return _advance_payment_fact_fields()


# ── Заявка на подотчётные средства ────────────────────────────────────────

def _accountable_funds_request_to(subject_id: int, status: str) -> None:
    from .services import accountable_funds_request_service as request_svc

    request = AccountableFundsRequest.objects.filter(pk=subject_id).first()
    if request is not None and request.status != status:
        request_svc.change_status(subject_id, status)


def _accountable_funds_request_on_started(subject_id: int) -> None:
    _accountable_funds_request_to(subject_id, AccountableFundsRequestStatus.ON_REVIEW)


def _accountable_funds_request_on_approved(subject_id: int) -> None:
    _accountable_funds_request_to(subject_id, AccountableFundsRequestStatus.AWAITING_ACCOUNTING)


def _accountable_funds_request_on_rejected(subject_id: int) -> None:
    _accountable_funds_request_to(subject_id, AccountableFundsRequestStatus.DRAFT)


def _accountable_funds_request_on_rework(subject_id: int) -> None:
    _accountable_funds_request_to(subject_id, AccountableFundsRequestStatus.DRAFT)


def _accountable_funds_request_on_cancelled(subject_id: int) -> None:
    _accountable_funds_request_to(subject_id, AccountableFundsRequestStatus.DRAFT)


def _describe_accountable_funds_request(subject_id: int) -> dict | None:
    request = (AccountableFundsRequest.objects.select_related("budget_line__budget__administrator", "budget_line__program")
               .filter(pk=subject_id).first())
    if request is None:
        return None
    return {
        "title": f"Заявка на подотчётные средства: {request.amount} ({request.budget_line.program.display_name})",
        "url": f"/contracts/accountable-funds-requests/{request.pk}",
    }


def _accountable_funds_request_facts(subject_id: int) -> dict:
    request = (AccountableFundsRequest.objects.select_related("budget_line__budget__administrator")
               .filter(pk=subject_id).first())
    if request is None:
        return {}
    return {
        "admin_country_id": request.budget_line.budget.administrator.country_id,
        "program_id": request.budget_line.program_id,
        "amount": request.amount,
    }


def _accountable_funds_request_fact_fields() -> list[dict]:
    return [
        {"key": "admin_country_id", "label": "Страна администратора",
         "type": "choice", "options": _country_options()},
        {"key": "program_id", "label": "Программа",
         "type": "choice", "options": _program_options()},
        {"key": "amount", "label": "Сумма", "type": "number"},
    ]


def _completion_act_to(subject_id: int, status: str) -> None:
    from .services import completion_act_service as act_svc

    act = CompletionAct.objects.filter(pk=subject_id).first()
    if act is not None and act.status != status:
        act_svc.change_status(subject_id, status)


def _completion_act_on_started(subject_id: int) -> None:
    _completion_act_to(subject_id, AdvancePaymentStatus.ON_REVIEW)


def _completion_act_on_approved(subject_id: int) -> None:
    _completion_act_to(subject_id, AdvancePaymentStatus.AWAITING_ACCOUNTING)


def _completion_act_on_rejected(subject_id: int) -> None:
    _completion_act_to(subject_id, AdvancePaymentStatus.DRAFT)


def _completion_act_on_rework(subject_id: int) -> None:
    _completion_act_to(subject_id, AdvancePaymentStatus.DRAFT)


def _completion_act_on_cancelled(subject_id: int) -> None:
    _completion_act_to(subject_id, AdvancePaymentStatus.DRAFT)


def _describe_completion_act(subject_id: int) -> dict | None:
    act = (CompletionAct.objects.select_related("agreement", "agreement__counterparty")
           .filter(pk=subject_id).first())
    if act is None:
        return None
    return {
        "title": f"Акт выполненных работ по договору {act.agreement.number} "
                 f"({act.amount} {act.agreement.currency})",
        "url": f"/contracts/completion-acts/{act.pk}",
    }


def _completion_act_facts(subject_id: int) -> dict:
    act = (CompletionAct.objects
           .select_related("agreement__budget_line__budget__administrator", "agreement__counterparty")
           .filter(pk=subject_id).first())
    if act is None:
        return {}
    agreement = act.agreement
    return {
        "admin_country_id": agreement.budget_line.budget.administrator.country_id,
        "counterparty_country_id": agreement.counterparty.country_id,
        "program_id": agreement.budget_line.program_id,
        "amount": act.amount,
        "currency": agreement.currency,
    }


def _completion_act_fact_fields() -> list[dict]:
    return _advance_payment_fact_fields()


def _invoice_facts(subject_id: int) -> dict:
    invoice = (Invoice.objects
               .select_related("budget_line__budget__administrator",
                               "counterparty")
               .filter(pk=subject_id).first())
    if invoice is None:
        return {}
    return {
        # Обе страны, названные по-разному, — по той же причине, что у
        # договора (см. докстринг модуля): общий ``country_id`` был бы ловушкой.
        "admin_country_id":
            invoice.budget_line.budget.administrator.country_id,
        "counterparty_country_id": invoice.counterparty.country_id,
        # Программа — со СТРОКИ бюджета; на самом счёте её колонки нет.
        "program_id": invoice.budget_line.program_id,
        "amount": invoice.amount,
        "currency": invoice.currency,
    }


def _invoice_fact_fields() -> list[dict]:
    countries = _country_options()  # один запрос на оба поля
    return [
        {"key": "admin_country_id", "label": "Страна администратора бюджета",
         "type": "choice", "options": countries},
        {"key": "counterparty_country_id", "label": "Страна контрагента",
         "type": "choice", "options": countries},
        {"key": "program_id", "label": "Программа",
         "type": "choice", "options": _program_options()},
        {"key": "amount", "label": "Сумма счёта", "type": "number"},
        {"key": "currency", "label": "Валюта", "type": "string"},
        # ``payment_type`` у счёта нет — счёт просто оплачивают, без типов
        # оплаты договора; ветку по нему предложить не из чего.
    ]


# ── describe: как объект выглядит в интерфейсе signoff ──────────────────
#
# URL'ы указывают на фронтовые маршруты contracts. Строятся здесь, а не во
# фронтенде: signoff показывает объекты РАЗНЫХ аппок в одном списке, и знать,
# куда ведёт каждый, может только его владелец.

def _describe_budget(subject_id: int) -> dict | None:
    """Согласуется бюджет ЦЕЛИКОМ, поэтому в заголовке — итог и число
    программ, а не одна строка: согласующий утверждает весь список."""
    budget = (Budget.objects
              .select_related("administrator", "administrator__country")
              .prefetch_related("lines")
              .filter(pk=subject_id).first())
    if budget is None:
        return None
    lines = list(budget.lines.all())
    totals = budget_calc.totals_for_budget(lines)
    return {
        "title": (f"Бюджет {budget.period_year}: {budget.administrator.display_name} "
                  f"— {totals['allocated']} {budget.currency} "
                  f"по {len(lines)} программам"),
        "url": f"/contracts/budgets/{budget.pk}",
    }


def _describe_counterparty(subject_id: int) -> dict | None:
    counterparty = Counterparty.objects.filter(pk=subject_id).first()
    if counterparty is None:
        return None
    return {
        # Признак НДС — в заголовке: согласующему по карточке контрагента
        # он нужен ровно так же, как БИН/ИИН (тот же набор, что и в __str__).
        "title": (f"Контрагент {counterparty.name} "
                  f"({counterparty.bin_iin}, {counterparty.vat_label})"),
        "url": f"/contracts/counterparties/{counterparty.pk}",
    }


def _describe_agreement(subject_id: int) -> dict | None:
    agreement = (Agreement.objects.select_related("counterparty")
                 .filter(pk=subject_id).first())
    if agreement is None:
        return None
    return {
        "title": (f"Договор {agreement.number} — {agreement.name} "
                  f"({agreement.counterparty.name}, {agreement.amount} "
                  f"{agreement.currency})"),
        "url": f"/contracts/agreements/{agreement.pk}",
    }


# ── facts: по чему signoff разрешено ветвить маршрут ────────────────────

def _country_options() -> list[dict]:
    """Справочник стран для редактора маршрута.

    Читается на каждый показ, а не кэшируется: страну заводят раз в год, а
    вот отсутствие только что заведённой страны в списке веток выглядит как
    поломка редактора.
    """
    return [{"value": country.pk, "label": country.name}
            for country in Country.objects.all()]


def _program_options() -> list[dict]:
    """Справочник программ для редактора маршрута.

    Подпись — ``display_name`` («код название»), та же, что в карточках и
    django-admin: программа, названная в ветке маршрута иначе, чем в бюджете,
    читалась бы как другая программа.

    Неактивные программы (``is_active=False``) отсюда НЕ отфильтрованы, хотя
    поле есть. Причина не в удобстве, а в том, что ``options`` — не только
    список для выпадашки: ``conditions._validate_value`` отбивает значение
    choice-поля, которого в нём нет. Спрятав снятую с учёта программу, мы
    сделали бы нередактируемым КАЖДЫЙ уже настроенный этап, который её
    называет, — 409 «неизвестные значения» при следующем сохранении, далеко
    от причины. Уже идущие процессы и сохранённые условия при этом
    продолжают работать: ``evaluate`` со справочником не сверяется.
    """
    return [{"value": program.pk, "label": program.display_name}
            for program in Program.objects.all()]


def _budget_facts(subject_id: int) -> dict:
    budget = (Budget.objects.select_related("administrator")
              .prefetch_related("lines").filter(pk=subject_id).first())
    if budget is None:
        # Пустые факты, а не исключение: объект удалили между отправкой и
        # запуском. Условный маршрут на этом откажет внятным «не сошлось ни
        # одно условие», безусловный отработает как прежде — решать, что
        # делать с висячей ссылкой, не задача этой функции.
        return {}
    return {
        "admin_country_id": budget.administrator.country_id,
        "period_year": budget.period_year,
        "currency": budget.currency,
        # Сумма бюджета — это сумма его строк (денег на самом Budget нет,
        # см. докстринг модели), поэтому она считается, а не читается полем.
        "amount": budget_calc.totals_for_budget(list(budget.lines.all()))["allocated"],
    }


def _budget_fact_fields() -> list[dict]:
    return [
        {"key": "admin_country_id", "label": "Страна администратора бюджета",
         "type": "choice", "options": _country_options()},
        {"key": "period_year", "label": "Год", "type": "number"},
        {"key": "currency", "label": "Валюта", "type": "string"},
        {"key": "amount", "label": "Сумма бюджета", "type": "number"},
    ]


def _counterparty_facts(subject_id: int) -> dict:
    counterparty = Counterparty.objects.filter(pk=subject_id).first()
    if counterparty is None:
        return {}
    return {
        "counterparty_country_id": counterparty.country_id,
        "vat": counterparty.vat,
    }


def _counterparty_fact_fields() -> list[dict]:
    return [
        {"key": "counterparty_country_id", "label": "Страна контрагента",
         "type": "choice", "options": _country_options()},
        {"key": "vat", "label": "Плательщик НДС", "type": "bool"},
    ]


def _agreement_facts(subject_id: int) -> dict:
    agreement = (Agreement.objects
                 .select_related("budget_line__budget__administrator",
                                 "counterparty")
                 .filter(pk=subject_id).first())
    if agreement is None:
        return {}
    return {
        # Обе страны, названные по-разному: см. докстринг модуля о том,
        # почему общий «country_id» здесь был бы ловушкой.
        "admin_country_id":
            agreement.budget_line.budget.administrator.country_id,
        "counterparty_country_id": agreement.counterparty.country_id,
        # Программа берётся со СТРОКИ бюджета — на самом договоре её нет
        # (одна версия правды о том, из какого кармана деньги). Лишнего
        # запроса не стоит: ``budget_line`` уже в select_related выше, а
        # ``program_id`` — колонка на ней.
        "program_id": agreement.budget_line.program_id,
        "amount": agreement.amount,
        "currency": agreement.currency,
        "payment_type": agreement.payment_type,
    }


def _agreement_fact_fields() -> list[dict]:
    countries = _country_options()  # один запрос на оба поля
    return [
        {"key": "admin_country_id", "label": "Страна администратора бюджета",
         "type": "choice", "options": countries},
        {"key": "counterparty_country_id", "label": "Страна контрагента",
         "type": "choice", "options": countries},
        {"key": "program_id", "label": "Программа",
         "type": "choice", "options": _program_options()},
        {"key": "amount", "label": "Сумма договора", "type": "number"},
        {"key": "currency", "label": "Валюта", "type": "string"},
        {"key": "payment_type", "label": "Тип оплаты", "type": "choice",
         "options": [{"value": value, "label": label}
                     for value, label in PaymentType.choices]},
    ]


def register() -> None:
    signoff.register_subject(
        Budget.SIGNOFF_SUBJECT_TYPE,
        label="Бюджет",
        model=Budget,
        describe=_describe_budget,
        facts=_budget_facts,
        fact_fields=_budget_fact_fields,
    )
    signoff.register_subject(
        Counterparty.SIGNOFF_SUBJECT_TYPE,
        label="Контрагент",
        model=Counterparty,
        describe=_describe_counterparty,
        facts=_counterparty_facts,
        fact_fields=_counterparty_fact_fields,
    )
    signoff.register_subject(
        Agreement.SIGNOFF_SUBJECT_TYPE,
        label="Договор",
        model=Agreement,
        on_started=_agreement_on_started,
        on_approved=_agreement_on_approved,
        on_rejected=_agreement_on_rejected,
        on_rework=_agreement_on_rework,
        on_cancelled=_agreement_on_cancelled,
        describe=_describe_agreement,
        facts=_agreement_facts,
        fact_fields=_agreement_fact_fields,
    )
    signoff.register_subject(
        Invoice.SIGNOFF_SUBJECT_TYPE,
        label="Счёт на оплату",
        model=Invoice,
        on_started=_invoice_on_started,
        on_approved=_invoice_on_approved,
        on_rejected=_invoice_on_rejected,
        on_rework=_invoice_on_rework,
        on_cancelled=_invoice_on_cancelled,
        describe=_describe_invoice,
        facts=_invoice_facts,
        fact_fields=_invoice_fact_fields,
    )
    signoff.register_subject(
        AdvancePayment.SIGNOFF_SUBJECT_TYPE,
        label="Предоплата на основании договора",
        model=AdvancePayment,
        on_started=_advance_payment_on_started,
        on_approved=_advance_payment_on_approved,
        on_rejected=_advance_payment_on_rejected,
        on_rework=_advance_payment_on_rework,
        on_cancelled=_advance_payment_on_cancelled,
        describe=_describe_advance_payment,
        facts=_advance_payment_facts,
        fact_fields=_advance_payment_fact_fields,
    )
    signoff.register_subject(
        AccountableFundsRequest.SIGNOFF_SUBJECT_TYPE,
        label="Заявка на подотчётные средства",
        model=AccountableFundsRequest,
        on_started=_accountable_funds_request_on_started,
        on_approved=_accountable_funds_request_on_approved,
        on_rejected=_accountable_funds_request_on_rejected,
        on_rework=_accountable_funds_request_on_rework,
        on_cancelled=_accountable_funds_request_on_cancelled,
        describe=_describe_accountable_funds_request,
        facts=_accountable_funds_request_facts,
        fact_fields=_accountable_funds_request_fact_fields,
    )
    signoff.register_subject(
        ContractPayment.SIGNOFF_SUBJECT_TYPE,
        label="Оплата по договору",
        model=ContractPayment,
        on_started=_contract_payment_on_started,
        on_approved=_contract_payment_on_approved,
        on_rejected=_contract_payment_on_rejected,
        on_rework=_contract_payment_on_rework,
        on_cancelled=_contract_payment_on_cancelled,
        describe=_describe_contract_payment,
        facts=_contract_payment_facts,
        fact_fields=_contract_payment_fact_fields,
    )
    signoff.register_subject(
        CompletionAct.SIGNOFF_SUBJECT_TYPE,
        label="Акт выполненных работ",
        model=CompletionAct,
        on_started=_completion_act_on_started,
        on_approved=_completion_act_on_approved,
        on_rejected=_completion_act_on_rejected,
        on_rework=_completion_act_on_rework,
        on_cancelled=_completion_act_on_cancelled,
        describe=_describe_completion_act,
        facts=_completion_act_facts,
        fact_fields=_completion_act_fact_fields,
    )
