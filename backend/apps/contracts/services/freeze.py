"""Заморозка раздела «Договоры» после переноса в модуль БЗО (A6.2, D-S6-4).

Признак — строка ``FreezeState`` в схеме компании: всё здесь работает в
текущем контексте компании (``search_path``), как и остальной ``contracts``.

Кто его читает:

- ``apps/contracts/middleware.py`` — запись под ``/api/contracts/``
  замороженной компании отвечает 403 ``contracts_frozen``, чтение идёт
  дальше;
- ``approval_hooks._guard`` — движок согласований живёт под
  ``/api/signoff/`` и middleware его не видит, поэтому запуск согласования
  документа раздела и возврат закрытого документа на доработку в
  замороженной компании закрывают колбэки предметов (тот же 403);
- ``GET contracts/v1/freeze`` — фронт прячет кнопки правки и переносит
  пункт меню в «Закупки и оплаты» (архив);
- ``FrozenReadOnlyAdminMixin`` (``admin.py``) — django-admin раздела
  только на чтение.

Заморозку не ставит, пока есть идущие согласования документов раздела:
решение по ним писало бы в замороженные таблицы (``PendingApprovals``;
``revoke_pending`` отзывает их движком перед заморозкой).

Старые команды раздела (``import_cashflow*``, ``seed_contracts_demo``)
компанию не принимают и работают в ``public`` — к заморозке компании
отношения не имеют; книгу CashFlow теперь грузит ``bpp_import_cashflow``.

Фоновых задач Celery у ``contracts`` нет (ни ``tasks.py``, ни расписаний) —
пропускать при заморозке нечего; появится задача — проверять ``is_frozen()``.

``ServiceStatus`` домена при заморозке не трогается: архив обязан читаться.
"""

from __future__ import annotations

import logging

from django.db import ProgrammingError, transaction
from django.utils import timezone
from psycopg import errors as pg_errors

from apps.contracts.models import FreezeState
from htqweb.errors import DomainError
from htqweb.fallback import fallback

logger = logging.getLogger(__name__)

FROZEN_CODE = "contracts_frozen"
FROZEN_DETAIL = ("Раздел перенесён в «Закупки и оплаты». "
                 "Данные доступны только для чтения.")


def current() -> FreezeState | None:
    return FreezeState.objects.filter(pk=FreezeState.SINGLETON_PK).first()


def is_frozen() -> bool:
    # Между выкаткой кода и ``migrate_companies`` таблицы в схеме компании ещё
    # нет, а признак спрашивается на КАЖДОЙ записи раздела у всех компаний:
    # без таблицы это «не заморожен», а не 500. Запрос — под точкой
    # сохранения: в Postgres упавший запрос отравляет всю транзакцию запроса.
    try:
        with transaction.atomic():
            return FreezeState.objects.filter(pk=FreezeState.SINGLETON_PK,
                                              frozen_at__isnull=False).exists()
    except ProgrammingError as exc:
        if not isinstance(exc.__cause__, pg_errors.UndefinedTable):
            raise
        return fallback("contracts.freeze.table_missing", False,
                        reason="таблицы заморозки в схеме компании ещё нет — "
                               "migrate_companies не прогнан",
                        expected=True, exc=exc)


class ContractsFrozen(DomainError):
    """Раздел заморожен — запись закрыта (403 ``contracts_frozen``)."""

    def __init__(self) -> None:
        super().__init__(FROZEN_CODE, FROZEN_DETAIL, status=403)


def assert_not_frozen() -> None:
    if is_frozen():
        raise ContractsFrozen()


class PendingApprovals(Exception):
    """Заморозке мешают идущие согласования документов раздела."""

    def __init__(self, documents: list[dict]) -> None:
        super().__init__(f"идущих согласований: {len(documents)}")
        self.documents = documents


def pending_documents() -> list[dict]:
    """Документы раздела на согласовании: ``[{subject_type, id, title}]``."""
    from apps.contracts import models as m
    from apps.signoff.interface import ApprovalState

    out = []
    for model in (m.Budget, m.Counterparty, m.Agreement, m.Invoice, m.AdvancePayment,
                  m.AccountableFundsRequest, m.AdvanceReport, m.ContractPayment,
                  m.CompletionAct, m.GoodsInvoice):
        for row in model.objects.filter(approval_state=ApprovalState.PENDING):
            out.append({"subject_type": model.SIGNOFF_SUBJECT_TYPE, "id": row.pk,
                        "title": str(row)})
    return out


def info() -> dict:
    """``{frozen, frozen_at, comment}`` — ответ ``GET contracts/v1/freeze``."""
    row = current()
    frozen = row is not None and row.frozen_at is not None
    return {"frozen": frozen,
            "frozen_at": row.frozen_at if frozen else None,
            "comment": row.comment if frozen else ""}


def freeze(*, actor_id: int | None = None, comment: str = "",
           revoke_pending: bool = False) -> bool:
    """Заморозить. ``True`` — заморозили сейчас, ``False`` — уже было.

    Повтор ничего не переписывает: дата и автор первой заморозки — то, что
    потом спросят («с какого дня раздел закрыт»), и повторный прогон
    ранбука не должен их сдвигать.

    Идущие согласования без ``revoke_pending`` не пускают —
    ``PendingApprovals`` со списком, раздел остаётся открытым. С ним их
    отзывает движок (документы — в черновик), и всё это одной транзакцией с
    заморозкой.
    """
    with transaction.atomic():
        row, _ = FreezeState.objects.select_for_update().get_or_create(
            pk=FreezeState.SINGLETON_PK)
        if row.frozen_at is not None:
            return False
        pending = pending_documents()
        if pending:
            if not revoke_pending:
                raise PendingApprovals(pending)
            from apps.contracts.services import migration_export

            for subject_type in {doc["subject_type"] for doc in pending}:
                migration_export.revoke(
                    subject_type,
                    [d["id"] for d in pending if d["subject_type"] == subject_type])
        row.frozen_at = timezone.now()
        row.frozen_by_id = actor_id
        row.comment = comment
        row.save()
    logger.info("contracts заморожен: actor=%s comment=%r", actor_id, comment)
    return True


def unfreeze(*, actor_id: int | None = None, comment: str = "") -> bool:
    """Снять заморозку (``contracts_freeze --undo``). ``True`` — сняли сейчас,
    ``False`` — раздел и не был заморожен."""
    with transaction.atomic():
        row = (FreezeState.objects.select_for_update()
               .filter(pk=FreezeState.SINGLETON_PK).first())
        if row is None or row.frozen_at is None:
            return False
        row.frozen_at = None
        row.frozen_by_id = None
        row.comment = comment
        row.save()
    logger.info("contracts разморожен: actor=%s comment=%r", actor_id, comment)
    return True
