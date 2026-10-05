"""Файл выписки — владелец ``bpp.bank_import`` в ``apps.files`` (ТЗ §11.2,
§21; план этапа 3 A, задача 3). Подключается сам: ``apps/bpp/file_owners.py``
находит ``services/<подмодуль>/file_owner.py`` и зовёт ``register()``
(решение D-S3-1).

- Тип ``bank_statement`` (TXT, XLSX, CSV до 20 МБ — справочник, миграция
  ``files/0004_bpp_stage3_file_types``), один документ на загрузку.
- Видит файл тот, кто видит загрузки выписок: ``bpp.bank`` view (ФД, БУХ).
- Менять файл нельзя никому: выписка — основание для строк загрузки, и
  после загрузки она неизменна. Файл кладёт сама загрузка
  (``services/bank/imports.py``) из кода; панель ``/api/files/v1`` его только
  показывает и выдаёт ссылку на скачивание.
- «Отправлялся» — всегда: загрузка не удаляется (ТЗ §15.5 — отменённая
  загрузка остаётся), и физически стереть её файл нечем.
"""

from __future__ import annotations

from apps.bpp.file_owners import actor_from_token, history_on_event
from apps.bpp.models.bank import BankImport
from apps.bpp.services.core import files as core_files
from apps.files import interface as files

__all__ = ["FILE_TYPE", "NODE", "OWNER", "register"]

OWNER = "bpp.bank_import"
FILE_TYPE = "bank_statement"
NODE = "bpp.bank"


def _can_view(owner_id, token) -> bool:
    return (BankImport.objects.filter(pk=owner_id).exists()
            and actor_from_token(token).can(NODE, "view"))


def _can_modify(owner_id, token) -> None:
    if not actor_from_token(token).can(NODE, "edit"):
        raise files.FilesForbidden(
            "Менять файлы загрузки выписки нельзя. Если это ошибка, обратитесь к "
            "администратору.")
    raise files.FilesLocked(
        "Файл выписки после загрузки не меняется. Чтобы загрузить другую выписку, "
        "создайте новую загрузку.")


def _was_sent(owner_id) -> bool:
    return True


def _lock(owner_id) -> None:
    # Только ключ: строка несёт ``source`` — до 20 МБ байтов выписки на время
    # разбора, и тянуть их ради блокировки незачем.
    (BankImport.objects.select_for_update().filter(pk=owner_id)
     .values_list("pk", flat=True).first())


def register() -> None:
    files.register_owner(
        OWNER, label="Загрузка выписки", service="bpp_bank", tenant=True,
        folder="bank-import", model=BankImport,
        file_types=(files.FileTypeSpec(FILE_TYPE, cardinality=files.SINGLE, required=True),),
        can_view=_can_view, can_modify=_can_modify, was_sent=_was_sent, lock=_lock,
        on_event=history_on_event(BankImport),
    )
    core_files.register_owner_type(BankImport, OWNER)
