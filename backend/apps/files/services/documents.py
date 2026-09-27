"""Документы объекта-владельца: папка, загрузка, версии, удаление, скачивание.

Что где решается
----------------
* **Видно ли объект и можно ли менять его файлы** — решает владелец
  (колбэки реестра). Подсистема лишь переводит его ответ в формат ТЗ: не
  видно → 404 (существование не раскрываем), нет прав → 403 ``E-ACC-01``,
  не тот статус → 409 ``E-FIL-06`` с текстом владельца.
* **Тип файла, формат, размер, количество** — справочник «Типы файлов»
  (формат и размер) плюс правила типа у владельца (``FileTypeSpec``:
  квота, «1 действующий + версии»). Проверяются до записи в хранилище, чтобы
  не класть байты зря, и повторно под блокировкой владельца.
* **Версии — по ТЗ.** Номер присваивается один раз (следующий по документу)
  под ``SELECT … FOR UPDATE`` строки владельца и не меняется никогда. Новая
  версия грузится поверх конкретной действующей (``base_file_id``); если ту
  уже заменили — 409 ``E-CON-01`` с именем и временем того, кто успел
  раньше. Повтор запроса с тем же ``Idempotency-Key`` возвращает первую
  запись (ТЗ §23, §26.2): ключ проверяется до записи в хранилище, ещё раз
  под блокировкой, и последний рубеж — уникальные индексы; их отказ тоже
  превращается в повтор или ``E-CON-01``, а не в 500.
* **Скачивание — только через временную ссылку, выданную на этот запрос**
  (``link``, ``DownloadFile`` из ТЗ). В ответах папки и загрузки готовых
  ссылок нет намеренно: ТЗ §25.2 требует журналировать скачивание, и
  заранее подписанная ссылка была бы скачиванием мимо журнала. Заодно ссылка
  не успевает протухнуть на долго открытой странице.
* **Удаление.** Документ ни разу не отправленного владельца удаляется
  физически (строки + файл в ``media.delete_file`` после коммита). После
  первой отправки — только ``deleted_at``: «файлы не удаляются физически
  после отправки документа» (ТЗ §21). ``media.delete_file`` для файлов
  подсистемы больше не зовётся нигде: soft-delete в media через грейс
  становится физическим.
* **Журнал** (ТЗ §25.2: «загрузка / замена / скачивание файлов», кто, когда,
  IP, user-agent) — ``FileEvent`` у каждого владельца и, если у владельца
  есть своя лента (заявка), событие ещё и туда (``on_event``), в той же
  транзакции.

Запись в хранилище — вне транзакции и вне блокировки (тот же довод, что у
``apps.signoff.services.attachments``): держать ``FOR UPDATE`` на владельце,
пока байты едут в S3, значит запереть его отправку на время сетевой
операции. Если под блокировкой отказ — сохранённый файл возвращается в media,
но только когда строка так и не появилась.
"""

from __future__ import annotations

import datetime as dt
import os
import uuid
from dataclasses import dataclass
from typing import Any
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.core.services import ServiceDisabled, require_service
# Соседи — только через interface (apps/core/tests/test_app_isolation.py).
from apps.companies import interface as companies
from apps.hr import interface as hr
from apps.media_files import interface as media
from apps.users import interface as users
from htqweb.fallback import fallback
from htqweb.tenancy import NoCompanyContext, current_company_or_none

from ..errors import (
    E_ACCESS, E_CONFLICT, E_FORMAT, E_INFECTED, E_LOCKED, E_QUOTA, E_SIZE,
    E_UNAVAILABLE, FilesError, bad_request, not_found,
)
from ..models import FileEvent, FileObject, FileType
from . import registry
from .registry import SINGLE, FilesForbidden, FilesLocked, OwnerEntry, FileTypeSpec

#: Scope media_files: потолок форматов и размера, ключ по папке владельца.
SCOPE = "file_object"
MB = 1024 * 1024
#: Даты в текстах — по времени Asia/Almaty (ТЗ стр. 11), хотя хранится UTC.
DISPLAY_TZ = ZoneInfo("Asia/Almaty")

#: MIME по расширению. Тип берётся ИЗ РАСШИРЕНИЯ, а не из заявленного
#: браузером: расширение уже проверено по справочнику, и сигнатура в media
#: сверит содержимое именно с ним — «договор.pdf» с байтами DOCX не пройдёт.
EXT_MIME = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    # Счёт-фактура (мастер-план БЗО, D-31 / ответ Q-C28): xml принимается, а
    # отдаётся только вложением — в список inline media он не входит.
    ".xml": "application/xml",
}
_EXT_LABEL = {".jpeg": "JPG"}

EVENT_ATTACHED = "file_attached"
EVENT_VERSION_ATTACHED = "file_version_attached"
EVENT_DELETED = "file_deleted"
EVENT_DOWNLOADED = "file_downloaded"
#: Загрузка отвергнута антивирусом — только журнал, не лента владельца:
#: документа не появилось, а попытка занести угрозу — событие аудита.
EVENT_REJECTED = "file_rejected"

OBJECT_NOT_FOUND = "Объект не найден. Возможно, он удалён или у вас нет к нему доступа."


@dataclass(frozen=True)
class OwnerRef:
    """Владелец, к которому обращаются в этом запросе."""

    entry: OwnerEntry
    # Ключ в типе ключа модели владельца (``OwnerEntry.native_id``): так его
    # получают колбэки владельца. В таблицах — строкой (``key``).
    owner_id: Any
    # Компания запроса: для тенантного владельца — часть ключа и фильтр
    # (``""`` — режим до tenancy_bootstrap), для общего — просто факт.
    company: str

    @property
    def key(self) -> str:
        """Ключ владельца так, как он лежит в ``FileObject.owner_id``."""
        return str(self.owner_id)


# ── общие куски ─────────────────────────────────────────────────────────

def formats_label(formats: list[str]) -> str:
    labels: list[str] = []
    for ext in formats:
        label = _EXT_LABEL.get(ext, ext.lstrip(".").upper())
        if label not in labels:
            labels.append(label)
    return ", ".join(labels)


def _moment(value: dt.datetime) -> str:
    """«в 14:32» сегодня, «23.09.2026 в 14:32» — в другой день."""
    local = value.astimezone(DISPLAY_TZ)
    if local.date() == timezone.now().astimezone(DISPLAY_TZ).date():
        return f"в {local:%H:%M}"
    return f"{local:%d.%m.%Y} в {local:%H:%M}"


def owner_company(entry: OwnerEntry) -> str:
    """Компания, к которой относятся файлы владельца в этом запросе.

    Для тенантного владельца компания — часть ключа, и подставлять её нельзя
    (CLAUDE.md: «контекст компании обязателен, а не подставляется»). Пока
    компаний нет вовсе (до ``tenancy_bootstrap`` тенантные таблицы живут в
    ``public``), честное значение — ``""``. Когда компании заведены, запрос к
    тенантному владельцу без контекста — это обход поддомена или задача без
    ``company_slug``: молча взять ``""`` значило бы читать и писать ничью
    «общую» кучу файлов, поэтому — ``NoCompanyContext``.
    """
    company = current_company_or_none()
    if company:
        return company
    if entry.tenant and companies.active_company_slugs():
        raise NoCompanyContext(
            f"Файлы {entry.owner_type!r} живут в схеме компании, а контекст "
            f"компании не установлен (запрос мимо поддомена или задача без "
            f"company_slug).")
    return ""


def resolve(owner_type: str, owner_id: Any, token) -> OwnerRef:
    """Владелец по ключу и проверка, что вызывающему он виден."""
    require_service("files")
    try:
        entry = registry.get_owner(owner_type)
    except registry.UnknownOwner:
        raise not_found(OBJECT_NOT_FOUND) from None
    require_service(entry.service)
    try:
        native = entry.native_id(owner_id)
    except registry.BadOwnerId:
        # Такого ключа у владельца не бывает — значит, нет и объекта.
        raise not_found(OBJECT_NOT_FOUND) from None
    ref = OwnerRef(entry=entry, owner_id=native, company=owner_company(entry))
    if not entry.can_view(ref.owner_id, token):
        raise not_found(OBJECT_NOT_FOUND)
    return ref


def _owner_qs(ref: OwnerRef):
    qs = FileObject.objects.filter(owner_type=ref.entry.owner_type,
                                   owner_id=ref.key)
    if ref.entry.tenant:
        # id тенантных владельцев повторяются в разных компаниях: без этого
        # фильтра файлы договора №6 одной компании видны в другой.
        qs = qs.filter(company_slug=ref.company)
    return qs


def _folder(ref: OwnerRef) -> str:
    """Папка владельца в хранилище: «1 объект = 1 папка».

    У общего владельца (заявка) id сквозные, поэтому сегмент компании —
    всегда ``public``: иначе файлы одной заявки, приложенные с разных
    поддоменов, разъехались бы по двум папкам.
    """
    company = (ref.company or "public") if ref.entry.tenant else "public"
    return f"{company}/{ref.entry.folder}/{ref.key}"


def assert_can_modify(ref: OwnerRef, token) -> None:
    try:
        ref.entry.can_modify(ref.owner_id, token)
    except FilesForbidden as exc:
        raise FilesError(E_ACCESS, 403, str(exc)) from exc
    except FilesLocked as exc:
        raise FilesError(E_LOCKED, 409, str(exc)) from exc


def _modify_block(ref: OwnerRef, token) -> FilesError | None:
    """Почему менять файлы нельзя — или ``None``, если можно."""
    try:
        assert_can_modify(ref, token)
    except FilesError as exc:
        return exc
    return None


def _file_types(entry: OwnerEntry) -> dict[str, FileType]:
    codes = [spec.code for spec in entry.file_types]
    rows = {row.code: row for row in FileType.objects.filter(code__in=codes)}
    missing = [code for code in codes if code not in rows]
    if missing:
        # Ошибка выкатки, а не пользователя: строки справочника заводятся
        # миграциями apps.files вместе с регистрацией владельца.
        raise ImproperlyConfigured(
            f"Типы файлов {missing} владельца {entry.owner_type!r} не заведены "
            f"в справочнике «Типы файлов» — не применена миграция apps.files")
    return rows


def _live(ref: OwnerRef) -> dict[uuid.UUID, str]:
    """Действующие (не удалённые) документы: ``{document_id: тип}``."""
    return dict(_owner_qs(ref).filter(deleted_at__isnull=True)
                .values_list("document_id", "file_type_id").distinct())


def _quota_error(ref: OwnerRef, spec: FileTypeSpec, live: dict[uuid.UUID, str],
                 types: dict[str, FileType]) -> FilesError | None:
    """Можно ли добавить ещё один документ этого типа. Версии не считаются."""
    if spec.cardinality == SINGLE and spec.code in live.values():
        return FilesError(
            E_QUOTA, 409,
            f"Файл «{types[spec.code].name}» уже приложен. Чтобы заменить его, "
            f"загрузите новую версию.",
            details={"file_type": spec.code})
    if spec.quota_group is not None:
        group = {s.code for s in ref.entry.file_types if s.quota_group == spec.quota_group}
        used = sum(1 for code in live.values() if code in group)
        limit = ref.entry.quotas[spec.quota_group]
        if used >= limit:
            return FilesError(
                E_QUOTA, 409,
                f"Уже приложено документов: {used} из {limit} — это предел. Удалите "
                f"лишний или загрузите новую версию существующего.",
                details={"group": spec.quota_group, "max": limit, "used": used})
    if spec.max_documents is not None:
        used = sum(1 for code in live.values() if code == spec.code)
        if used >= spec.max_documents:
            return FilesError(
                E_QUOTA, 409,
                f"Документов «{types[spec.code].name}» уже {used} из "
                f"{spec.max_documents} — это предел. Удалите лишний или загрузите "
                f"новую версию существующего.",
                details={"file_type": spec.code, "max": spec.max_documents, "used": used})
    return None


def version_out(row: FileObject) -> dict:
    return {
        "id": row.pk,
        "document_id": str(row.document_id),
        "file_type": row.file_type_id,
        "version_no": row.version_no,
        "is_replaced": row.is_replaced,
        "replaced_by_id": row.replaced_by_id,
        "name": row.name,
        "mime": row.mime,
        "size": row.size,
        "sha256": row.sha256,
        "storage_key": row.storage_key,
        "uploaded_by_id": row.uploaded_by_id,
        "uploaded_by_name": row.uploaded_by_name,
        "uploaded_by_department_id": row.uploaded_by_department_id,
        "uploaded_by_department_name": row.uploaded_by_department_name,
        "uploaded_at": row.uploaded_at.isoformat(),
        "deleted_at": row.deleted_at.isoformat() if row.deleted_at else None,
    }


def _journal_only(ref: OwnerRef, event: str, actor_id: int | None, payload: dict,
                  audit: dict | None) -> None:
    """Запись только в журнал файлов — для событий без документа (отказ)."""
    audit = audit or {}
    FileEvent.objects.create(
        company_slug=ref.company, owner_type=ref.entry.owner_type,
        owner_id=ref.key, event=event, document_id=payload.get("document_id"),
        actor_id=actor_id, payload=payload, ip=(audit.get("ip") or "")[:64],
        user_agent=(audit.get("user_agent") or "")[:300])


def _event(ref: OwnerRef, event: str, actor_id: int | None, payload: dict,
           audit: dict | None) -> None:
    """Запись в журнал файлов и в ленту владельца — одной точкой сохранения:
    журнал без ленты или лента без журнала хуже, чем ни того ни другого."""
    audit = audit or {}
    with transaction.atomic():
        FileEvent.objects.create(
            company_slug=ref.company,
            owner_type=ref.entry.owner_type,
            owner_id=ref.key,
            event=event,
            document_id=payload.get("document_id"),
            file_id=payload.get("file_id"),
            actor_id=actor_id,
            payload=payload,
            ip=(audit.get("ip") or "")[:64],
            user_agent=(audit.get("user_agent") or "")[:300],
        )
        if ref.entry.on_event is not None:
            ref.entry.on_event(ref.owner_id, event, actor_id, {**payload, **audit})


# ── чтение ──────────────────────────────────────────────────────────────

def folder(owner_type: str, owner_id: Any, token) -> dict:
    """Папка владельца: документы с версиями, типы, квоты, что можно делать.

    Документы — в порядке первого вложения; удалённые (после отправки они
    только помечаются) — в конце: история того, что видели согласующие, не
    пропадает. Версии внутри документа — от новой к старой.
    """
    ref = resolve(owner_type, owner_id, token)
    entry = ref.entry
    types = _file_types(entry)
    rows = list(_owner_qs(ref).order_by("document_id", "version_no"))

    grouped: dict[uuid.UUID, list[FileObject]] = {}
    for row in rows:
        grouped.setdefault(row.document_id, []).append(row)

    documents = []
    for document_id, versions in grouped.items():
        current = versions[-1]
        file_type = types.get(current.file_type_id)
        documents.append({
            "document_id": str(document_id),
            "file_type": current.file_type_id,
            "file_type_name": file_type.name if file_type else current.file_type_id,
            "deleted_at": current.deleted_at.isoformat() if current.deleted_at else None,
            "current": version_out(current),
            "versions": [version_out(v) for v in reversed(versions)],
            "_first": min(v.pk for v in versions),
        })
    documents.sort(key=lambda d: (d["deleted_at"] is not None, d["_first"]))
    for document in documents:
        del document["_first"]

    block = _modify_block(ref, token)
    can_modify = block is None
    # Причину показываем, только когда дело в состоянии объекта («меняются
    # только в черновике…»): это подсказка автору. Отказ по правам читателю
    # (согласующему, наблюдателю) объяснять незачем — он ничего не пытался.
    reason = block.message if block is not None and block.code == E_LOCKED else None
    live = {uuid.UUID(d["document_id"]): d["file_type"]
            for d in documents if d["deleted_at"] is None}
    types_out = []
    for spec in entry.file_types:
        row = types[spec.code]
        blocked = None if not can_modify else _quota_error(ref, spec, live, types)
        types_out.append({
            "code": spec.code,
            "name": row.name,
            "formats": list(row.formats),
            "max_mb": row.max_mb,
            "cardinality": spec.cardinality,
            "required": spec.required,
            "quota_group": spec.quota_group,
            "can_add": can_modify and blocked is None,
            "reason": reason if not can_modify else (blocked.message if blocked else None),
        })
    quotas = []
    for group, limit in entry.quotas.items():
        codes = {s.code for s in entry.file_types if s.quota_group == group}
        quotas.append({"group": group, "max": limit,
                       "used": sum(1 for code in live.values() if code in codes)})

    return {
        "owner_type": entry.owner_type,
        "owner_id": ref.key,
        "storage_prefix": f"{SCOPE}/{_folder(ref)}/",
        "can_modify": can_modify,
        "modify_reason": reason,
        "delete_is_physical": not entry.was_sent(ref.owner_id),
        "types": types_out,
        "quotas": quotas,
        "documents": documents,
    }


def link(owner_type: str, owner_id: Any, document_id, file_id: int, token,
         audit: dict | None = None) -> dict:
    """``DownloadFile`` (ТЗ стр. 68): временная ссылка после проверки прав.

    Каждая выдача — событие ``file_downloaded`` в журнал владельца (ТЗ
    §25.2): ссылка выдаётся на конкретное скачивание, других путей к байтам
    у файлов подсистемы нет (media отдаёт их только по такой ссылке —
    ``owner_gated``). Удалённые после отправки версии тоже отдаются — это
    история документа.
    """
    ref = resolve(owner_type, owner_id, token)
    row = _owner_qs(ref).filter(document_id=document_id, pk=file_id).first()
    if row is None:
        raise not_found()
    item = media.get_file_links([row.media_file_id]).get(row.media_file_id)
    if item is None:
        raise not_found("Файл не найден в хранилище. Обратитесь к администратору.")
    _event(ref, EVENT_DOWNLOADED, token.user_id, {
        "document_id": str(row.document_id), "file_id": row.pk, "name": row.name,
        "file_type": row.file_type_id, "version_no": row.version_no,
    }, audit)
    return {"url": item["url"],
            "expires_at": dt.datetime.fromtimestamp(item["exp"], tz=dt.timezone.utc).isoformat()}


# ── запись ──────────────────────────────────────────────────────────────

def _current_or_404(ref: OwnerRef, document_id) -> FileObject:
    current = _owner_qs(ref).filter(document_id=document_id).order_by("-version_no").first()
    if current is None or current.deleted_at is not None:
        raise not_found("Документ не найден — возможно, его удалили. Обновите страницу.")
    return current


def _assert_base_is_current(current: FileObject, base_id: int) -> None:
    if current.pk == base_id:
        return
    who = (f"пользователем {current.uploaded_by_name}" if current.uploaded_by_name
           else "другим пользователем")
    raise FilesError(
        E_CONFLICT, 409,
        f"Документ изменён {who} {_moment(current.uploaded_at)}. Ваши изменения не "
        f"сохранены. Обновите страницу и внесите их повторно.",
        details={"current_file_id": current.pk,
                 "replaced_by_name": current.uploaded_by_name,
                 "replaced_at": current.uploaded_at.isoformat()})


def _base_id(raw) -> int:
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise bad_request(
            "Не указано, поверх какой версии загружается новая. Обновите страницу "
            "и повторите загрузку.", field="base_file_id") from None


def _replay(ref: OwnerRef, key: str, *, document_id, file_type: str | None) -> FileObject | None:
    """Первая запись с этим ключом повтора — или ``None``.

    Ключ ставится на одно действие пользователя: этот файл в это место.
    Запись по тому же ключу, но в другое место (другой документ, другой тип)
    — ошибка клиента, а не повтор; отдать её молча значило бы ответить «файл
    приложен» про чужой файл.
    """
    if not key:
        return None
    row = _owner_qs(ref).filter(idempotency_key=key).first()
    if row is None:
        return None
    same_target = (row.document_id == document_id if document_id is not None
                   else row.version_no == 1 and row.file_type_id == file_type)
    if not same_target:
        raise bad_request(
            "Этот ключ повтора уже использован для другого файла. Обновите страницу "
            "и повторите загрузку.", details={"idempotency_key": key})
    return row


def precheck(owner_type: str, owner_id: Any, token, *, document_id=None) -> OwnerRef:
    """Всё, что решается без самого файла, — ДО разбора тела запроса: чужому
    (404) и читателю (403/409) незачем занимать воркер, пока multipart
    раскладывается и 20 МБ читаются в память."""
    ref = resolve(owner_type, owner_id, token)
    assert_can_modify(ref, token)
    if document_id is not None:
        _current_or_404(ref, document_id)
    return ref


def _uploader(token) -> dict:
    return _uploader_snapshot(token.user_id, token.username or token.email or "")


def _uploader_snapshot(user_id: int, fallback_name: str = "") -> dict:
    """«Кто загрузил» + снимок ФИО и отдела на момент загрузки.

    Снимок, а не ссылка: «кто из какого отдела приложил» должно переживать
    перевод и увольнение. Недоступный users/hr стоит снимку ФИО или отдела,
    но не загрузки.
    """
    name = None
    try:
        rows = users.get_users_brief([user_id])
        name = rows[0]["full_name"] if rows else None
    except ServiceDisabled as exc:
        fallback("files.documents.uploader_name", None, expected=True, exc=exc,
                 reason="users выключен — ФИО загрузившего не записано")
    except Exception as exc:
        fallback("files.documents.uploader_name", None, exc=exc,
                 reason="users не ответил — ФИО загрузившего не записано")

    department_id, department_name = None, ""
    try:
        employee = hr.get_employee_brief(user_id)
        if employee and employee.get("department_id"):
            department_id = employee["department_id"]
            department = hr.get_department_brief(department_id) or {}
            department_name = department.get("name") or ""
    except (ServiceDisabled, NotImplementedError) as exc:
        fallback("files.documents.uploader_department", None, expected=True, exc=exc,
                 reason="hr выключен — отдел загрузившего не записан")
    except Exception as exc:
        fallback("files.documents.uploader_department", None, exc=exc,
                 reason="hr не ответил — отдел загрузившего не записан")

    return {
        "uploaded_by_id": user_id,
        "uploaded_by_name": name or fallback_name,
        "uploaded_by_department_id": department_id,
        "uploaded_by_department_name": department_name,
    }


def _store(ref: OwnerRef, *, data: bytes, name: str, ext: str, mime: str,
           actor_id: int, file_type: FileType) -> dict:
    """Запись в media (scope ``file_object``: папка владельца, антивирус).

    Отказы media — в формат ТЗ. Антивирус проверяет байты там же, до записи
    (``ScopePolicy.antivirus``): угроза — 422 ``E-FIL-08``, молчащий сканер —
    503 ``E-SYS-01``, и файл в обоих случаях не сохраняется.
    """
    try:
        return media.store_file(data=data, filename=name, mime=mime, scope=SCOPE,
                                owner_id=actor_id, folder=_folder(ref))
    except media.FileInfected as exc:
        raise FilesError(
            E_INFECTED, 422,
            f"Файл {name} не загружен: антивирус обнаружил угрозу «{exc.signature}». "
            f"Проверьте файл и компьютер антивирусом и загрузите чистую копию.",
            fields=[{"field": "file", "message": "Обнаружена угроза"}],
            details={"signature": exc.signature}) from exc
    except media.ScanUnavailable as exc:
        raise FilesError(
            E_UNAVAILABLE, 503,
            f"Файл {name} не загружен: проверка на вирусы сейчас недоступна, а без "
            f"неё файлы не принимаются. Повторите загрузку через несколько минут.",
            details={"reason": exc.detail}) from exc
    except ValueError as exc:
        status = getattr(exc, "status_code", None)
        if status is None:
            raise
        reason = {"reason": getattr(exc, "detail", str(exc))}
        field = [{"field": "file", "message": "Файл не принят"}]
        if status == 413:
            # Текст — дословно ТЗ §13.2: у формата и размера он один.
            raise FilesError(
                E_SIZE, 413,
                f"Файл {name} не загружен: допустимы {formats_label(file_type.formats)} "
                f"до {file_type.max_mb} МБ.",
                fields=field, details=reason) from exc
        if status == 415:
            raise FilesError(
                E_FORMAT, 415,
                f"Файл {name} не загружен: содержимое не соответствует формату "
                f"{formats_label([ext])}. Проверьте, что файл не повреждён и не "
                f"переименован, и загрузите его снова.",
                fields=field, details=reason) from exc
        raise bad_request(
            f"Файл {name} не загружен: хранилище его не приняло. Проверьте файл и "
            f"повторите загрузку.", field="file", details=reason) from exc


def _discard(media_file_id: str) -> None:
    """Вернуть в media файл, к документу не привязанный (или отвязанный при
    физическом удалении). ``delete_file`` — soft-delete; физически байты
    стирает грейс media."""
    try:
        media.delete_file(media_file_id)
    except ServiceDisabled as exc:
        fallback("files.documents.discard_failed", None, expected=True, exc=exc,
                 reason="media выключен — файл не вернулся в media и останется без владельца",
                 media_file_id=media_file_id)
    except Exception as exc:
        fallback("files.documents.discard_failed", None, exc=exc,
                 reason="файл не вернулся в media и останется без владельца",
                 media_file_id=media_file_id)


def _discard_after_commit(media_file_ids: list[str]) -> None:
    """``_discard`` после коммита — ``robust``: сбой возврата одного файла
    не должен ни ронять уже закоммиченное действие (ответ был бы 500 при
    успешном удалении), ни мешать вернуть остальные."""
    for media_file_id in media_file_ids:
        transaction.on_commit(lambda media_file_id=media_file_id: _discard(media_file_id),
                              robust=True)


def _discard_unless_linked(media_file_id: str) -> None:
    """``_discard`` после отказа — только если строка так и не появилась.

    Ошибка не всегда значит откат: обрыв соединения на уже исполненном
    COMMIT выглядит так же. Стереть тогда файл, на который ссылается
    документ, значило бы через грейс media физически удалить, возможно, уже
    отправленное. Не удалось проверить — файл остаётся: лишний байт дешевле
    потерянного документа.
    """
    try:
        linked = FileObject.objects.filter(media_file_id=media_file_id).exists()
    except Exception as exc:
        fallback("files.documents.link_check_failed", None, exc=exc,
                 reason="не удалось проверить, привязан ли файл, — он оставлен в media",
                 media_file_id=media_file_id)
        return
    if not linked:
        _discard(media_file_id)


def upload(ref: OwnerRef, token, *, upload, file_type: str | None = None,
           document_id=None, base_file_id=None, idempotency_key: str = "",
           audit: dict | None = None) -> FileObject:
    """``UploadFile`` (ТЗ стр. 68): новый документ или новая версия.

    ``ref`` — уже проверенный ``precheck`` владелец.
    """
    key = (idempotency_key or "").strip()[:64]
    replay = _replay(ref, key, document_id=document_id, file_type=file_type)
    if replay is not None:
        return replay
    if upload is None:
        raise bad_request("Не выбран файл. Выберите файл и повторите загрузку.",
                          field="file")

    types = _file_types(ref.entry)
    base_id = None
    if document_id is None:
        spec = ref.entry.spec(file_type or "")
        if spec is None:
            raise bad_request(
                f"Неизвестный тип файла «{file_type or ''}». Выберите тип из списка и "
                f"повторите загрузку.", field="file_type")
    else:
        base_id = _base_id(base_file_id)
        current = _current_or_404(ref, document_id)
        _assert_base_is_current(current, base_id)
        spec = ref.entry.spec(current.file_type_id)
        if spec is None:
            raise ImproperlyConfigured(
                f"Тип {current.file_type_id!r} больше не объявлен владельцем "
                f"{ref.entry.owner_type!r}")
    ftype = types[spec.code]

    name = os.path.basename((upload.name or "").replace("\\", "/")) or "file"
    ext = os.path.splitext(name)[1].lower()
    if ext not in ftype.formats:
        raise FilesError(
            E_FORMAT, 415,
            f"Файл {name} не загружен: допустимы {formats_label(ftype.formats)} до "
            f"{ftype.max_mb} МБ.",
            fields=[{"field": "file", "message": "Недопустимый формат"}],
            details={"formats": list(ftype.formats), "max_mb": ftype.max_mb})
    if upload.size > ftype.max_mb * MB:
        # Текст — дословно ТЗ §13.2: у формата и размера он один; сколько
        # весит файл, интерфейс берёт из ``details``.
        raise FilesError(
            E_SIZE, 413,
            f"Файл {name} не загружен: допустимы {formats_label(ftype.formats)} до "
            f"{ftype.max_mb} МБ.",
            fields=[{"field": "file", "message": "Слишком большой файл"}],
            details={"size": upload.size, "max_mb": ftype.max_mb})
    if document_id is None:
        blocked = _quota_error(ref, spec, _live(ref), types)
        if blocked is not None:
            raise blocked

    data = upload.read()
    uploader = _uploader(token)
    try:
        stored = _store(ref, data=data, name=name, ext=ext,
                        mime=EXT_MIME.get(ext, "application/octet-stream"),
                        actor_id=token.user_id, file_type=ftype)
    except FilesError as exc:
        if exc.code == E_INFECTED:
            _journal_only(ref, EVENT_REJECTED, token.user_id, {
                "name": name, "file_type": spec.code, "reason": "infected",
                "signature": exc.details.get("signature", ""),
                "document_id": str(document_id) if document_id else None,
            }, audit)
        raise
    try:
        return _link(ref, token, stored=stored, name=name, spec=spec, key=key,
                     document_id=document_id, base_id=base_id, uploader=uploader,
                     audit=audit)
    except Exception:
        _discard_unless_linked(str(stored["id"]))
        raise


@transaction.atomic
def _link(ref: OwnerRef, token, *, stored: dict, name: str, spec: FileTypeSpec,
          key: str, document_id, base_id: int | None, uploader: dict,
          audit: dict | None) -> FileObject:
    ref.entry.lock(ref.owner_id)
    media_file_id = str(stored["id"])
    replay = _replay(ref, key, document_id=document_id, file_type=spec.code)
    if replay is not None:
        # Параллельный повтор успел раньше: его запись и есть ответ, а
        # только что сохранённый файл — лишний.
        _discard_after_commit([media_file_id])
        return replay
    # За время записи в хранилище владельца могли отправить.
    assert_can_modify(ref, token)

    current = None
    if document_id is None:
        blocked = _quota_error(ref, spec, _live(ref), _file_types(ref.entry))
        if blocked is not None:
            raise blocked
        target_document = uuid.uuid4()
        version_no = 1
    else:
        current = _current_or_404(ref, document_id)
        _assert_base_is_current(current, base_id)
        target_document = document_id
        version_no = current.version_no + 1

    try:
        # Точка сохранения: отказ уникального индекса не должен убить
        # внешнюю транзакцию — после него нужно перечитать, кто успел.
        with transaction.atomic():
            row = FileObject.objects.create(
                company_slug=ref.company,
                owner_type=ref.entry.owner_type,
                owner_id=ref.key,
                file_type_id=spec.code,
                document_id=target_document,
                version_no=version_no,
                name=name,
                mime=stored["mime"],
                size=int(stored["size"]),
                sha256=stored["sha256"],
                storage_key=stored["path"],
                media_file_id=media_file_id,
                idempotency_key=key,
                **uploader,
            )
    except IntegrityError:
        # Сюда доходит только гонка мимо блокировки владельца (владелец, чей
        # lock ничего не блокирует): повтор с тем же ключом успел раньше —
        # отдать его; версию успели загрузить раньше — E-CON-01.
        replay = _replay(ref, key, document_id=document_id, file_type=spec.code)
        if replay is not None:
            _discard_after_commit([media_file_id])
            return replay
        if document_id is not None:
            _assert_base_is_current(_current_or_404(ref, document_id), base_id)
        raise
    if current is not None:
        FileObject.objects.filter(pk=current.pk).update(is_replaced=True, replaced_by=row)

    payload = {"document_id": str(target_document), "file_id": row.pk, "name": row.name,
               "file_type": spec.code, "version_no": version_no}
    if current is not None:
        payload["replaced_file_id"] = current.pk
    _event(ref, EVENT_VERSION_ATTACHED if current is not None else EVENT_ATTACHED,
           token.user_id, payload, audit)
    return row


def delete(owner_type: str, owner_id: Any, document_id, token,
           audit: dict | None = None) -> None:
    """Удалить документ со всеми версиями (см. модуль: физически или пометкой)."""
    ref = resolve(owner_type, owner_id, token)
    assert_can_modify(ref, token)
    with transaction.atomic():
        ref.entry.lock(ref.owner_id)
        assert_can_modify(ref, token)
        rows = list(_owner_qs(ref).filter(document_id=document_id).order_by("version_no"))
        if not rows:
            raise not_found()
        live = [row for row in rows if row.deleted_at is None]
        if not live:
            return  # уже удалён после отправки — повтор ничего не меняет
        current = rows[-1]
        physical = not ref.entry.was_sent(ref.owner_id)
        if physical:
            FileObject.objects.filter(pk__in=[row.pk for row in rows]).delete()
            _discard_after_commit([row.media_file_id for row in rows])
        else:
            FileObject.objects.filter(pk__in=[row.pk for row in live]).update(
                deleted_at=timezone.now(), deleted_by_id=token.user_id)
        _event(ref, EVENT_DELETED, token.user_id, {
            "document_id": str(document_id),
            "name": current.name,
            "file_type": current.file_type_id,
            "versions": len(rows),
            "physical": physical,
        }, audit)


# ── для владельцев и выкатки ────────────────────────────────────────────

def owner_ref(owner_type: str, owner_id: Any) -> OwnerRef:
    """Владелец без проверки прав — для вызовов из самого владельца (удаление
    объекта, перенос старых файлов), где права уже проверил он сам."""
    require_service("files")
    entry = registry.get_owner(owner_type)
    return OwnerRef(entry=entry, owner_id=entry.native_id(owner_id),
                    company=owner_company(entry))


def purge_owner(ref: OwnerRef, actor_id: int | None) -> None:
    """Владелец удаляет сам объект — что станет с его файлами.

    Та же развилка, что у удаления одного документа: ни разу не
    отправленный объект уносит файлы с собой физически (строки + файлы в
    media после коммита), отправлявшийся — нет (ТЗ §21: «файлы не удаляются
    физически после отправки»): его документы получают ``deleted_at`` и
    остаются — объекта больше нет, а история того, что к нему прикладывали,
    есть.

    Зовётся в транзакции удаления объекта, ДО удаления его строки: и
    ``was_sent``, и блокировка читают эту строку. Блокировка — первой:
    иначе загрузка, успевшая взять её раньше, вставила бы файл уже после
    того, как здесь прочитали список, — к объекту, которого не станет.
    """
    with transaction.atomic():
        ref.entry.lock(ref.owner_id)
        rows = list(_owner_qs(ref).order_by("document_id", "version_no"))
        if not rows:
            return
        physical = not ref.entry.was_sent(ref.owner_id)
        grouped: dict[uuid.UUID, list[FileObject]] = {}
        for row in rows:
            grouped.setdefault(row.document_id, []).append(row)
        if physical:
            FileObject.objects.filter(pk__in=[row.pk for row in rows]).delete()
            _discard_after_commit([row.media_file_id for row in rows])
        else:
            FileObject.objects.filter(
                pk__in=[row.pk for row in rows if row.deleted_at is None],
            ).update(deleted_at=timezone.now(), deleted_by_id=actor_id)
        for document_id, versions in grouped.items():
            if not physical and all(v.deleted_at is not None for v in versions):
                continue  # удалён раньше — вторая запись о том же не нужна
            current = versions[-1]
            _event(ref, EVENT_DELETED, actor_id, {
                "document_id": str(document_id),
                "name": current.name,
                "file_type": current.file_type_id,
                "versions": len(versions),
                "physical": physical,
                "reason": "owner_deleted",
            }, None)


def adopt(ref: OwnerRef, *, file_type: str, media_file_id: str,
          uploaded_by_id: int | None = None) -> tuple[FileObject, bool]:
    """Перенести файл, уже лежащий в media (старое поле владельца), в папку
    владельца — версией 1 нового документа.

    Байты КОПИРУЮТСЯ в scope ``file_object`` (``media.copy_file``): там их
    раскладка по папке и ``owner_gated``, а оригинал остаётся на месте —
    удалять его решает тот, кто переносит. Кто и когда загрузил — от
    оригинала, а не «сейчас и система»: это история документа.

    Повтор с тем же файлом ничего не делает — ключ повтора
    ``adopt:<id файла>`` под уникальным индексом. Возвращает
    ``(строка, создана_сейчас)``.
    """
    spec = ref.entry.spec(file_type)
    if spec is None:
        raise ValueError(f"Тип {file_type!r} не объявлен владельцем {ref.entry.owner_type!r}")
    key = f"adopt:{media_file_id}"[:64]
    existing = _owner_qs(ref).filter(idempotency_key=key).first()
    if existing is not None:
        return existing, False
    blocked = _quota_error(ref, spec, _live(ref), _file_types(ref.entry))
    if blocked is not None:
        raise blocked

    copied = media.copy_file(media_file_id, scope=SCOPE, folder=_folder(ref),
                             owner_id=uploaded_by_id)
    stored_id = str(copied["id"])
    try:
        who = uploaded_by_id if uploaded_by_id is not None else copied["source"]["owner_id"]
        if who is None:
            raise ValueError("не известно, кто загрузил файл: у оригинала нет владельца")
        with transaction.atomic():
            ref.entry.lock(ref.owner_id)
            existing = _owner_qs(ref).filter(idempotency_key=key).first()
            if existing is not None:
                _discard_after_commit([stored_id])
                return existing, False
            row = FileObject.objects.create(
                company_slug=ref.company,
                owner_type=ref.entry.owner_type,
                owner_id=ref.key,
                file_type_id=spec.code,
                document_id=uuid.uuid4(),
                version_no=1,
                name=copied["original_filename"] or "file",
                mime=copied["mime"],
                size=int(copied["size"]),
                sha256=copied["sha256"] or "",
                storage_key=copied["path"],
                media_file_id=stored_id,
                idempotency_key=key,
                **_uploader_snapshot(who),
            )
            FileObject.objects.filter(pk=row.pk).update(
                uploaded_at=dt.datetime.fromisoformat(copied["source"]["created_at"]))
            row.refresh_from_db()
            _event(ref, EVENT_ATTACHED, None, {
                "document_id": str(row.document_id), "file_id": row.pk,
                "name": row.name, "file_type": spec.code, "version_no": 1,
                "adopted_from": str(media_file_id),
            }, None)
    except Exception:
        _discard_unless_linked(stored_id)
        raise
    return row, True


def owners_with_documents(owner_type: str, owner_ids,
                          file_type: str | None = None) -> set:
    """Какие из объектов имеют хоть один действующий документ (этого типа) —
    одним запросом на весь список, а не запросом на строку. Ключи — в типе
    ключа модели владельца."""
    require_service("files")
    entry = registry.get_owner(owner_type)
    ids = [entry.storage_id(owner_id) for owner_id in owner_ids]
    if not ids:
        return set()
    qs = FileObject.objects.filter(owner_type=owner_type, owner_id__in=ids,
                                   deleted_at__isnull=True)
    if entry.tenant:
        qs = qs.filter(company_slug=owner_company(entry))
    if file_type is not None:
        qs = qs.filter(file_type_id=file_type)
    return {entry.native_id(key) for key in qs.values_list("owner_id", flat=True).distinct()}


def assign_company(slug: str, *, dry_run: bool = False) -> dict:
    """``tenancy_bootstrap``: файлам тенантных владельцев, заведённым до
    первой компании (``company_slug=""``), — компанию, в которую переезжают
    их владельцы. Возвращает ``{"files": n, "events": m}``.

    Ключи в хранилище не переносятся: у S3 нет переименования, а одноразовая
    команда в окне обслуживания не должна гонять байты. Файлы, приложенные
    до bootstrap, остаются под ``file_object/public/<папка>/<id>/``, новые
    ложатся под ``file_object/<slug>/…`` — фильтр по компании от этого не
    зависит.
    """
    tenant_types = [entry.owner_type for entry in registry.registered_owners().values()
                    if entry.tenant]
    files_qs = FileObject.objects.filter(company_slug="", owner_type__in=tenant_types)
    events_qs = FileEvent.objects.filter(company_slug="", owner_type__in=tenant_types)
    counts = {"files": files_qs.count(), "events": events_qs.count()}
    if not dry_run:
        files_qs.update(company_slug=slug)
        events_qs.update(company_slug=slug)
    return counts


# ── справочник «Типы файлов» ────────────────────────────────────────────

def type_out(row: FileType) -> dict:
    found = registry.spec_for(row.code)
    spec = found[1] if found else None
    return {
        "code": row.code,
        "owner_type": row.owner_type,
        "name": row.name,
        "formats": list(row.formats),
        "max_mb": row.max_mb,
        "sort_order": row.sort_order,
        "cardinality": spec.cardinality if spec else None,
        "required": spec.required if spec else None,
        "quota_group": spec.quota_group if spec else None,
    }


def types_list(owner_type: str | None = None) -> list[dict]:
    require_service("files")
    qs = FileType.objects.all()
    if owner_type:
        qs = qs.filter(owner_type=owner_type)
    return [type_out(row) for row in qs]


def types_update(code: str, max_mb, token) -> dict:
    """Администратор меняет только размер (ТЗ стр. 61: «Нет / размеры / нет»).

    Потолок — ``FILES_UPLOAD_CEILING_MB``: больше не пропустят ни шлюз
    (``client_max_body_size`` в nginx), ни scope ``file_object`` в media.
    """
    require_service("files")
    # Право проверил гейт модуля у ручки (``files.types`` → ``write``).
    row = FileType.objects.filter(pk=code).first()
    if row is None:
        raise not_found("Тип файла не найден. Обновите страницу.")
    ceiling = settings.FILES_UPLOAD_CEILING_MB
    if isinstance(max_mb, bool) or not isinstance(max_mb, int) or not 1 <= max_mb <= ceiling:
        raise bad_request(
            f"Размер должен быть целым числом от 1 до {ceiling} МБ: больший файл не "
            f"пропустит шлюз.", field="max_mb", details={"max": ceiling})
    row.max_mb = max_mb
    row.updated_by_id = token.user_id
    row.save(update_fields=["max_mb", "updated_by_id", "updated_at"])
    return type_out(row)
