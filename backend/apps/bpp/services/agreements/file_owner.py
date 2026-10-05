"""Файлы договора — владелец ``bpp.agreement`` в ``apps.files`` (ТЗ §21;
контракт мастер-плана §2.6, D-S3-1). Подключается сам: ``apps/bpp/file_owners.py``
находит ``services/<подмодуль>/file_owner.py`` и зовёт ``register()``.

- ``agreement`` — скан договора (у допсоглашения — самого допсоглашения):
  PDF, DOCX, JPG, PNG до 20 МБ, «1 действующий + версии», **обязателен для
  отправки** (``agreements.submit`` → ``core_files.require_files``, 422
  ``E-FIL-04``).
- ``agreement_annex`` — приложения, до 30.
- ``alternative_offer`` — КП выбранной альтернативы, до 5: переезжает в новый
  договор при выборе (B5.1, D-B51-7) загрузкой из кода.
- Видит файлы тот, кто видит договор (``agreements.can_view``: автор, его
  проекты и группы статей, директора и БУХ, согласующие).
- Менять через панель может автор, пока договор правится («Черновик», «На
  доработке»): замена — новой версией «до „Действует“» (ТЗ §21), на
  согласовании документы не меняются, как и сам договор.
- «Отправлялся» — договор уже уходил на согласование: его файлы при удалении
  не стираются физически.
"""

from __future__ import annotations

from apps.bpp.file_owners import actor_from_token, history_on_event
from apps.bpp.models import Agreement, AgreementStatus
from apps.bpp.services.core import files as core_files
from apps.files import interface as files
from apps.signoff import interface as signoff

from . import agreements as service

__all__ = ["ANNEX_TYPE", "FILE_TYPE", "KP_TYPE", "OWNER", "register"]

OWNER = "bpp.agreement"
FILE_TYPE = "agreement"
ANNEX_TYPE = "agreement_annex"
#: КП альтернативы, по которой создан договор (B5.1).
KP_TYPE = "alternative_offer"


def _agreement(owner_id) -> Agreement | None:
    return Agreement.objects.filter(pk=owner_id).first()


def _can_view(owner_id, token) -> bool:
    agr = _agreement(owner_id)
    return agr is not None and service.can_view(actor_from_token(token), agr)


def _can_modify(owner_id, token) -> None:
    agr = _agreement(owner_id)
    if agr is None or agr.author_id != token.user_id:
        raise files.FilesForbidden(
            "Файлы договора меняет его автор. Если это ошибка, обратитесь к "
            "администратору.")
    if agr.status == AgreementStatus.ON_REVIEW:
        raise files.FilesLocked(
            f"Договор {agr.number} на согласовании — файлы не меняются. Чтобы заменить "
            f"документ, отзовите договор или дождитесь возврата на доработку.")
    if agr.status not in service.EDITABLE:
        raise files.FilesLocked(
            f"Файлы договора {agr.number} меняются только в статусах «Черновик» и «На "
            f"доработке». Изменить действующий договор — допсоглашением.")


def _was_sent(owner_id) -> bool:
    agr = _agreement(owner_id)
    if agr is None:
        return False
    return (agr.status != AgreementStatus.DRAFT
            or signoff.get_process_for(Agreement.SIGNOFF_SUBJECT_TYPE, str(agr.pk)) is not None)


def _lock(owner_id) -> None:
    Agreement.objects.select_for_update().filter(pk=owner_id).values_list("pk", flat=True).first()


def register() -> None:
    files.register_owner(
        OWNER, label="Договор", service="bpp_agreements", tenant=True,
        folder="agreement", model=Agreement,
        file_types=(files.FileTypeSpec(FILE_TYPE, cardinality=files.SINGLE, required=True),
                    files.FileTypeSpec(ANNEX_TYPE, max_documents=30),
                    files.FileTypeSpec(KP_TYPE, max_documents=5)),
        can_view=_can_view, can_modify=_can_modify, was_sent=_was_sent, lock=_lock,
        on_event=history_on_event(Agreement),
    )
    core_files.register_owner_type(Agreement, OWNER)
