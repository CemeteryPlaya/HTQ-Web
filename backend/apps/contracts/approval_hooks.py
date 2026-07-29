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
"""

from __future__ import annotations

import logging

from apps.signoff import interface as signoff

from .models import Agreement, AgreementStatus, Budget, Counterparty

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
    # отклонённый договор дорабатывают и отправляют снова, а «расторгнут»
    # — состояние, из которого выхода нет.
    _agreement_to(subject_id, AgreementStatus.DRAFT)


def _agreement_on_cancelled(subject_id: int) -> None:
    _agreement_to(subject_id, AgreementStatus.DRAFT)


# ── describe: как объект выглядит в интерфейсе signoff ──────────────────
#
# URL'ы указывают на фронтовые маршруты contracts. Строятся здесь, а не во
# фронтенде: signoff показывает объекты РАЗНЫХ аппок в одном списке, и знать,
# куда ведёт каждый, может только его владелец.

def _describe_budget(subject_id: int) -> dict | None:
    budget = (Budget.objects
              .select_related("administrator", "administrator__country", "program")
              .filter(pk=subject_id).first())
    if budget is None:
        return None
    return {
        "title": (f"Бюджет {budget.period_year}: {budget.administrator.display_name} / "
                  f"{budget.program.name} — {budget.amount} {budget.currency}"),
        "url": f"/contracts/budgets/{budget.pk}",
    }


def _describe_counterparty(subject_id: int) -> dict | None:
    counterparty = Counterparty.objects.filter(pk=subject_id).first()
    if counterparty is None:
        return None
    return {
        "title": f"Контрагент {counterparty.name} ({counterparty.bin_iin})",
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


def register() -> None:
    signoff.register_subject(
        Budget.SIGNOFF_SUBJECT_TYPE,
        label="Бюджетная строка",
        model=Budget,
        describe=_describe_budget,
    )
    signoff.register_subject(
        Counterparty.SIGNOFF_SUBJECT_TYPE,
        label="Контрагент",
        model=Counterparty,
        describe=_describe_counterparty,
    )
    signoff.register_subject(
        Agreement.SIGNOFF_SUBJECT_TYPE,
        label="Договор",
        model=Agreement,
        on_started=_agreement_on_started,
        on_approved=_agreement_on_approved,
        on_rejected=_agreement_on_rejected,
        on_cancelled=_agreement_on_cancelled,
        describe=_describe_agreement,
    )
