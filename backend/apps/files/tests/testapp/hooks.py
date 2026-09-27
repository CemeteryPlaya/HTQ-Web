"""Регистрация пробных владельцев — образец того, что напишет настоящий
владелец (документы модуля БЗО).

``EVENTS`` — журнал колбэка ``on_event``: по нему тесты проверяют, что
файловые события доходят до владельца (у заявки это была её лента).
Строки справочника «Типы файлов» заводит ``seed_types()`` (фикстура
``conftest.py``): у тестовой аппки нет миграций, а у подсистемы — сидов
чужих типов.
"""

from __future__ import annotations

from apps.files import interface as files

from .models import ProbeFolder, UuidProbeFolder

OWNER = "filestest.folder"
UUID_OWNER = "filestest.uuidfolder"
QUOTA = "folder"
MAX_DOCUMENTS = 20
FORMATS = [".pdf", ".docx", ".xlsx", ".jpg", ".jpeg", ".png"]
TYPES = (
    # (код, название, порядок, форматы, владелец)
    ("probe.kp", "КП", 10, FORMATS, OWNER),
    ("probe.tz", "ТЗ", 20, FORMATS, OWNER),
    ("probe.spec", "Спецификация", 30, FORMATS, OWNER),
    ("probe.other", "Прочее", 40, FORMATS, OWNER),
    ("probe.doc", "Документ", 10, [".pdf"], UUID_OWNER),
)
_EDITABLE = (ProbeFolder.DRAFT, ProbeFolder.RETURNED)

EVENTS: list[tuple] = []


def reset() -> None:
    EVENTS.clear()


def seed_types() -> None:
    from apps.files.models import FileType

    for code, name, order, formats, owner in TYPES:
        FileType.objects.update_or_create(
            code=code, defaults={"owner_type": owner, "name": name,
                                 "formats": formats, "max_mb": 20, "sort_order": order})


# ── папка с целым ключом ────────────────────────────────────────────────

def _folder(owner_id: int) -> ProbeFolder | None:
    return ProbeFolder.objects.filter(pk=owner_id).first()


def _can_view(owner_id: int, token) -> bool:
    folder = _folder(owner_id)
    return folder is not None and (token.user_id == folder.author_id
                                   or token.user_id in folder.viewer_ids)


def _can_modify(owner_id: int, token) -> None:
    folder = _folder(owner_id)
    if folder is None or folder.author_id != token.user_id:
        raise files.FilesForbidden(
            "Менять файлы может только автор документа; если это ошибка, "
            "обратитесь к администратору.")
    if folder.status not in _EDITABLE:
        raise files.FilesLocked(
            f"Файлы документа {folder.code} меняются только в статусах «Черновик» "
            f"и «На доработке».")


def _was_sent(owner_id: int) -> bool:
    folder = _folder(owner_id)
    return folder is not None and folder.sent_at is not None


def _lock(owner_id: int) -> None:
    ProbeFolder.objects.select_for_update().filter(pk=owner_id).first()


def _on_event(owner_id: int, event: str, actor_id: int | None, payload: dict) -> None:
    EVENTS.append((owner_id, event, actor_id, payload))


# ── папка с UUID-ключом ─────────────────────────────────────────────────

def _uuid_can_view(owner_id, token) -> bool:
    return UuidProbeFolder.objects.filter(pk=owner_id, author_id=token.user_id).exists()


def _uuid_can_modify(owner_id, token) -> None:
    if not _uuid_can_view(owner_id, token):
        raise files.FilesForbidden("Менять файлы может только автор документа.")


def _uuid_lock(owner_id) -> None:
    UuidProbeFolder.objects.select_for_update().filter(pk=owner_id).first()


def register() -> None:
    files.register_owner(
        OWNER, label="Пробная папка", service="files", tenant=False, folder="folder",
        file_types=tuple(files.FileTypeSpec(code, quota_group=QUOTA)
                         for code, *_rest, owner in TYPES if owner == OWNER),
        quotas={QUOTA: MAX_DOCUMENTS},
        can_view=_can_view, can_modify=_can_modify, was_sent=_was_sent,
        lock=_lock, on_event=_on_event,
    )
    files.register_owner(
        UUID_OWNER, label="Пробная папка с UUID", service="files", tenant=False,
        folder="uuidfolder", model=UuidProbeFolder,
        file_types=(files.FileTypeSpec("probe.doc", cardinality=files.SINGLE),),
        can_view=_uuid_can_view, can_modify=_uuid_can_modify,
        was_sent=lambda owner_id: False, lock=_uuid_lock,
    )
