"""Документы модуля БЗО — владельцы файлов платформенной ``apps.files``.

Зовётся из ``BppConfig.ready()`` рядом с ``approval_hooks.register()``. Одна
файловая подсистема на платформу (план этапа 2 A, задача 1): файлы заявки и
авансового отчёта лежат в ``apps.files``, видны на её панели
``/api/files/v1/<владелец>/<id>/files/`` и журналируются там же. Сервисы
модуля прикладывают их через обёртку ``services/core/files.py``.

Правила ТЗ §21 — здесь (``FileTypeSpec``: сколько документов, «1 действующий
+ версии», обязательность); форматы и размеры — в справочнике «Типы
файлов» (миграция ``files/0003_bpp_file_types``). Типы договора, счёта и
прочих документов §21 регистрируются вместе с их документами (этап 3):

    ============================  ====================  ======  =====
    тип                            форматы               МБ      шт.
    ============================  ====================  ======  =====
    agreement — договор            PDF DOCX JPG PNG      20      1 (+ версии)
    agreement_annex — приложение   PDF DOCX JPG PNG      20      30
    invoice — счёт на оплату       PDF JPG PNG           10      5
    act — АВР                      PDF JPG PNG           10      10
    waybill — накладная            PDF JPG PNG           10      10
    vat_invoice — счёт-фактура     PDF JPG PNG XML       10      10
    bank_statement — выписка       TXT XLSX CSV          20      1
    alternative_offer — КП         PDF DOCX XLSX JPG PNG 20      5
    ============================  ====================  ======  =====

Колбэки владельца — поверх правил самих документов (``services/requests``,
``services/accountable``), без второй копии: кто видит документ — тот видит
и его файлы (ТЗ §21). Менять файлы через панель может автор и только пока
документ правится; сервисы модуля прикладывают файлы из кода по своим
правилам (новая версия документа заявки — и после отправки), подсистема их
при этом не переспрашивает.

Колбэки получают токен, а права модуля считаются от запроса (``Actor``):
запрос здесь — токен плюс компания текущего контекста.
"""

from __future__ import annotations

from types import SimpleNamespace

from apps.bpp.models import (
    AccountableStatus,
    AdvanceReport,
    PurchaseRequest,
    RequestStatus,
)
from apps.bpp.services.accountable import accountable as accountable_service
from apps.bpp.services.actor import Actor
from apps.bpp.services.core import audit
from apps.bpp.services.core import files as core_files
from apps.bpp.services.requests import requests as request_service
from apps.files import interface as files
from apps.signoff import interface as signoff
from htqweb.errors import DomainError
from htqweb.tenancy import current_company_or_none

REQUEST_OWNER = "bpp.purchase_request"
REPORT_OWNER = "bpp.advance_report"

#: Событие файловой подсистемы → запись в «Историю изменений» документа.
#: Скачивания туда не пишутся: их журнал — ``FileEvent`` подсистемы, а в
#: истории документа они утопили бы правки.
_AUDIT_ACTIONS = {
    "file_attached": "file_attached",
    "file_version_attached": "file_replaced",
    "file_deleted": "file_deleted",
}


def _actor(token) -> Actor:
    """``Actor`` из токена колбэка: права модуля считаются по компании
    текущего контекста, как у ручки модуля."""
    company = current_company_or_none()
    return Actor(SimpleNamespace(token=token,
                                 company={"slug": company} if company else None))


def _on_event(model):
    def record(owner_id, event: str, actor_id: int | None, payload: dict) -> None:
        action = _AUDIT_ACTIONS.get(event)
        if action is None:
            return
        changes = {"file_type": payload.get("file_type"), "filename": payload.get("name")}
        if payload.get("file_id") is not None:
            changes["file"] = str(payload["file_id"])
        if event == "file_version_attached":
            changes["previous"] = str(payload.get("replaced_file_id"))
            changes["version"] = payload.get("version_no")
        if event == "file_deleted":
            changes["versions"] = payload.get("versions")
            changes["physical"] = payload.get("physical")
        audit.record_for(model._meta.label_lower, str(owner_id), action,
                         actor_id=actor_id, changes=changes)
    return record


# ── заявка на закупку ───────────────────────────────────────────────────

def _request(owner_id) -> PurchaseRequest | None:
    return PurchaseRequest.objects.filter(pk=owner_id).first()


def _request_can_view(owner_id, token) -> bool:
    req = _request(owner_id)
    return req is not None and request_service.can_view(_actor(token), req)


def _request_can_modify(owner_id, token) -> None:
    req = _request(owner_id)
    if req is None or req.author_id != token.user_id:
        raise files.FilesForbidden(
            "Менять документы заявки может только её автор. Если это ошибка, "
            "обратитесь к администратору.")
    if req.status not in request_service.EDITABLE:
        raise files.FilesLocked(
            f"Документы заявки {req.number} добавляются и удаляются только в статусах "
            f"«Черновик» и «На доработке». Чтобы заменить документ отправленной "
            f"заявки, загрузите его новую версию в карточке заявки.")


def _request_was_sent(owner_id) -> bool:
    """Отправлялась ли заявка: не черновик — или черновик после отзыва
    (процесс согласования у неё уже был)."""
    req = _request(owner_id)
    if req is None:
        return False
    return (req.status != RequestStatus.DRAFT
            or signoff.get_process_for(PurchaseRequest.SIGNOFF_SUBJECT_TYPE,
                                       str(req.pk)) is not None)


def _request_lock(owner_id) -> None:
    PurchaseRequest.objects.select_for_update().filter(pk=owner_id).first()


# ── авансовый отчёт (подотчёт) ──────────────────────────────────────────

def _report(owner_id) -> AdvanceReport | None:
    return AdvanceReport.objects.select_related("request").filter(pk=owner_id).first()


def _report_can_view(owner_id, token) -> bool:
    try:
        accountable_service.get_visible_report(_actor(token), owner_id)
    except DomainError:
        return False
    return True


def _report_can_modify(owner_id, token) -> None:
    report = _report(owner_id)
    if report is None or report.request.accountable_user_id != token.user_id:
        raise files.FilesForbidden(
            "Менять файл авансового отчёта может только подотчётное лицо — автор "
            "заявки. Если это ошибка, обратитесь к администратору.")
    if (not report.is_editable
            or report.request.status != AccountableStatus.AWAITING_REPORT):
        raise files.FilesLocked(
            "Файл авансового отчёта меняется только до отправки отчёта на "
            "согласование.")


def _report_was_sent(owner_id) -> bool:
    report = _report(owner_id)
    if report is None:
        return False
    return (report.approval_state != signoff.ApprovalState.DRAFT
            or signoff.get_process_for(AdvanceReport.SIGNOFF_SUBJECT_TYPE,
                                       str(report.pk)) is not None)


def _report_lock(owner_id) -> None:
    AdvanceReport.objects.select_for_update().filter(pk=owner_id).first()


def register() -> None:
    files.register_owner(
        REQUEST_OWNER, label="Заявка на закупку", service="bpp_requests", tenant=True,
        folder="purchase-request", model=PurchaseRequest,
        # ТЗ §21: КП, ТЗ, спецификация, прочее — PDF, DOCX, XLSX, JPG, PNG до
        # 20 МБ, до 20 документов на заявку; версии в предел не входят.
        file_types=(files.FileTypeSpec("request_attachment", quota_group="documents"),),
        quotas={"documents": 20},
        can_view=_request_can_view, can_modify=_request_can_modify,
        was_sent=_request_was_sent, lock=_request_lock,
        on_event=_on_event(PurchaseRequest),
    )
    files.register_owner(
        REPORT_OWNER, label="Авансовый отчёт", service="bpp_accountable", tenant=True,
        folder="advance-report", model=AdvanceReport,
        # Один подтверждающий документ на отчёт (B4.1): PDF, JPG, PNG до 10 МБ.
        file_types=(files.FileTypeSpec("advance_report", cardinality=files.SINGLE,
                                       required=True),),
        can_view=_report_can_view, can_modify=_report_can_modify,
        was_sent=_report_was_sent, lock=_report_lock,
        on_event=_on_event(AdvanceReport),
    )
    core_files.register_owner_type(PurchaseRequest, REQUEST_OWNER)
    core_files.register_owner_type(AdvanceReport, REPORT_OWNER)
