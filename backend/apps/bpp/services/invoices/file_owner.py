"""Файлы счёта на оплату — владелец ``bpp.invoice`` в ``apps.files`` (ТЗ §21,
§10.2; контракт мастер-плана §2.6, D-S3-1). Подключается сам:
``apps/bpp/file_owners.py`` находит ``services/<подмодуль>/file_owner.py`` и
зовёт ``register()``.

- ``invoice`` — счёт контрагента: PDF, JPG, PNG до 10 МБ, до 5, **обязателен
  для «Отправить ФД»** (``invoices.submit`` → ``core_files.require_files``,
  422 ``E-FIL-04``). Меняет автор в «Черновике» и после возврата на
  доработку; после отправки — только помеченное удаление (ТЗ §21 «до „На
  рассмотрении ФД“ — удаление; далее — нет»: был отправлен → файл остаётся).
- ``act`` (АВР), ``waybill`` (накладная), ``vat_invoice`` (счёт-фактура, D-13)
  — закрывающие, до 10 каждого. **Видят только автор, ФД и БУХ** (ТЗ §21:
  «Автор, ФД, БУХ»; ТД, ОД и ГД видят сам счёт, но не закрывающие) — плюс
  держатель ``bpp.invoices.closing_docs``, который вкладывает их от имени
  автора. Вкладываются, когда бухгалтер их запросил (статус «Ждёт закрывающих
  документов»), и только запрошенные типы; после возврата БУХ — снова в этом
  статусе. «Документы предоставлены» (``payments.submit_docs``) проверяет,
  что по каждому запрошенному типу вложен хоть один файл (``E-INV-04``).
- ``alternative_offer`` — КП выбранной альтернативы, до 5: переезжает в
  новый счёт при выборе (B5.1, D-B51-7) загрузкой из кода; правила — как у
  файла счёта.
- Видит файлы счёта тот, кто видит счёт (``invoices.can_view``).
"""

from __future__ import annotations

from apps.bpp.file_owners import actor_from_token, history_on_event
from apps.bpp.models import Invoice, InvoiceStatus
from apps.bpp.services.core import files as core_files
from apps.files import interface as files
from apps.signoff import interface as signoff

from . import invoices as service
from .payments import DOC_FILE_TYPES, DOC_TYPES

__all__ = ["CLOSING_TYPES", "FILE_TYPE", "KP_TYPE", "OWNER", "register"]

OWNER = "bpp.invoice"
FILE_TYPE = "invoice"
#: КП альтернативы, по которой создан счёт (B5.1).
KP_TYPE = "alternative_offer"
#: Тип файла закрывающего документа → ключ ``Invoice.docs_required``.
CLOSING_TYPES = {file_type: key for key, file_type in DOC_FILE_TYPES.items()}


def _invoice(owner_id) -> Invoice | None:
    return Invoice.objects.filter(pk=owner_id).first()


def _closing_editor(actor, inv: Invoice) -> bool:
    """Вкладывает закрывающие автор счёта; ФД — от его имени (ТЗ §10.1 [Л])."""
    return inv.author_id == actor.user_id or actor.can("bpp.invoices.closing_docs", "edit")


def _can_view(owner_id, token) -> bool:
    inv = _invoice(owner_id)
    return inv is not None and service.can_view(actor_from_token(token), inv)


def _can_view_type(owner_id, token, file_type) -> bool:
    if file_type not in CLOSING_TYPES:
        return True
    inv = _invoice(owner_id)
    if inv is None:
        return False
    actor = actor_from_token(token)
    return (_closing_editor(actor, inv) or actor.can("bpp.invoices.decision", "edit")
            or actor.can("bpp.invoices.payment", "edit"))


def _can_modify(owner_id, token) -> None:
    """Может ли человек менять в папке хоть что-то сейчас; узкое правило по
    типу — в ``_can_modify_type``."""
    inv = _invoice(owner_id)
    actor = actor_from_token(token)
    if inv is None or not _closing_editor(actor, inv):
        raise files.FilesForbidden(
            "Файлы счёта вкладывает его автор. Если это ошибка, обратитесь к "
            "администратору.")
    if inv.status in service.EDITABLE and inv.author_id == actor.user_id:
        return
    if inv.status == InvoiceStatus.AWAITING_DOCS:
        return
    raise files.FilesLocked(
        f"Файлы счёта {inv.number} сейчас не меняются: счёт — в «Черновике» и после "
        f"возврата на доработку, закрывающие документы — когда их запросил бухгалтер.")


def _can_modify_type(owner_id, token, file_type) -> bool:
    inv = _invoice(owner_id)
    if inv is None:
        return False
    actor = actor_from_token(token)
    if file_type not in CLOSING_TYPES:
        if inv.status not in service.EDITABLE:
            raise files.FilesLocked(
                f"Файл счёта {inv.number} после отправки ФД не меняется. Нужен другой "
                f"документ — попросите вернуть счёт на доработку.")
        if inv.author_id != actor.user_id:
            raise files.FilesForbidden("Файл счёта меняет автор счёта.")
        return True
    if inv.status != InvoiceStatus.AWAITING_DOCS:
        raise files.FilesLocked(
            f"Закрывающие документы по счёту {inv.number} вкладываются, когда их "
            f"запросил бухгалтер (статус «Ждёт закрывающих документов»).")
    key = CLOSING_TYPES[file_type]
    if not (inv.docs_required or {}).get(key):
        raise files.FilesLocked(
            f"Бухгалтер не запрашивал «{DOC_TYPES[key]}» по счёту {inv.number}.")
    return True


def _was_sent(owner_id) -> bool:
    inv = _invoice(owner_id)
    if inv is None:
        return False
    return (inv.status != InvoiceStatus.DRAFT
            or signoff.get_process_for(Invoice.SIGNOFF_SUBJECT_TYPE, str(inv.pk)) is not None)


def _lock(owner_id) -> None:
    Invoice.objects.select_for_update().filter(pk=owner_id).values_list("pk", flat=True).first()


def register() -> None:
    files.register_owner(
        OWNER, label="Счёт на оплату", service="bpp_invoices", tenant=True,
        folder="invoice", model=Invoice,
        file_types=(files.FileTypeSpec(FILE_TYPE, max_documents=5, required=True),
                    *(files.FileTypeSpec(code, max_documents=10) for code in CLOSING_TYPES),
                    files.FileTypeSpec(KP_TYPE, max_documents=5)),
        can_view=_can_view, can_modify=_can_modify, was_sent=_was_sent, lock=_lock,
        on_event=history_on_event(Invoice),
        can_view_type=_can_view_type, can_modify_type=_can_modify_type,
    )
    core_files.register_owner_type(Invoice, OWNER)
