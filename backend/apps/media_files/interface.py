"""Публичный API аппки media_files для ДРУГИХ аппок.

Единственный способ, которым сосед (task/hr/messenger — все три вешают
файлы) имеет право обращаться к media_files. Прямой импорт
apps.media_files.models / apps.media_files.services из другой аппки
запрещён и ловится тестом apps/core/tests/test_app_isolation.py.

Каждая функция начинается с require_service("media"): если аппка
выключена, вызывающий получит ServiceDisabled, который api_view превратит
в 503-конверт (а не в 500) — см. htqweb/http.py. Это тот же контракт, что
и у apps.cms.interface / apps.users.interface — см. их докстринги для
полного объяснения.

store_file() запускает ТОТ ЖЕ пайплайн загрузки, что и
``views.upload_file`` (POST /api/media/v1/files/): валидацию/нормализацию
делает apps.media_files.services.upload_service.upload_file_bytes (никакой
копии логики здесь), после чего — если получившийся FileMetadata картинка
и у scope есть variants — так же ставит apps.media_files.tasks.make_variants
в очередь и пишет запись в audit-журнал, byte-for-byte та же побочка, что и
у HTTP-эндпоинта (за вычетом самого HTTP-request'а: owner_id передаётся
явно вызывающим, а не берётся из JWT, и audit.record_action получает
request=None — тот принимает это штатно, см. его докстринг).

get_file_meta() отдаёт имя/mime/размер файла — соседу, который его
ПОКАЗЫВАЕТ, а не просто ссылается (карточка договора рисует PDF во фрейме, а
картинку в img, и способ показа выбирается по mime).

get_file_url() переиспользует ровно ту же "signed vs plain" развилку, что
и views.issue_signed_url (через общий services.url_service.build_file_url)
— никакого самодельного HMAC здесь, как и предупреждает докстринг
htqweb.storage.signed_url. Импортируется из services/url_service.py, а не
из views.py (final review фаз 2-3, Finding 3) — публичный interface не
должен тянуть за собой HTTP-слой.

delete_file() — best-effort soft-delete на стороне соседа (сейчас
единственный вызывающий — apps.users.services.profile_service.
delete_avatar_object, после того как save_avatar/store_file стали
единственным писателем аватарок — final review фаз 2-3, Finding 1/2).
Полноценный DELETE-эндпоинт (PATCH/DELETE /{file_id}) вне скоупа задачи
3.3 и здесь не появляется — только soft-delete самой записи, необходимый
соседям для best-effort очистки.

Все функции возвращают только простые dict/str/bool, никогда ORM-объекты
FileMetadata — сосед не должен получить возможность мутировать чужую
модель напрямую.
"""

from __future__ import annotations

import logging
import uuid

from django.utils import timezone

from apps.core.services import require_service
from apps.media_files.models import FileMetadata
from apps.media_files.schemas import serialize_file
from apps.media_files.services import audit
from apps.media_files.services.scope_policy import authorize_scope_write
from apps.media_files.services.upload_service import (
    FileInfected,
    ScanUnavailable,
    UploadValidationError,
    read_original,
    upload_file_bytes,
)

# Отказы пайплайна, которые соседу надо различать: заражённый файл и
# недоступный антивирус (scope с ``ScopePolicy.antivirus``) — оба подклассы
# ``UploadValidationError`` (ValueError) со своим ``status_code``.
__all__ = [
    "FileInfected", "ScanUnavailable", "UploadValidationError",
    "store_file", "copy_file", "get_file_url", "get_file_links", "get_file_meta",
    "delete_file",
]
from apps.media_files.services.url_service import build_file_url

logger = logging.getLogger(__name__)


def store_file(*, data: bytes, filename: str, mime: str, scope: str,
                owner_id: int | None, internal_authorized: bool = False,
                folder: str | None = None) -> dict:
    """Run the upload pipeline on behalf of a neighbour app and hand back a
    plain dict shaped like the HTTP upload response
    (``schemas.FileMetadataRead``, at least ``{id, url, mime, size,
    is_public}`` — see that schema for the full field list).

    ``folder`` — папка объекта-владельца для scope с раскладкой «папка на
    владельца» (``ScopePolicy.folder_layout``, например ``file_object``):
    ключ ложится в ``<scope>/<folder>/<uuid>/original<ext>``, и все файлы
    одного объекта оказываются под одним префиксом. Для такого scope папка
    обязательна, для остальных — запрещена (422 ``UploadValidationError``).

    **R5 authorization contract (decision Д1):** this function goes through
    the same ``scope_policy.authorize_scope_write`` seam as the HTTP upload
    endpoint (``views.upload_file``), so a neighbour app can't silently write
    a restricted scope (``hr_doc``/``hr_department``/``task_attachment``) by
    accident. Because ``store_file`` is a service-to-service call with no
    request/JWT of its own to read ``is_elevated`` off of, the caller must
    assert authorization explicitly: pass ``internal_authorized=True`` to
    mean "the calling domain has already checked its own role/ownership
    rules for this write and vouches for it". Without it, a restricted-scope
    call raises ``django.core.exceptions.PermissionDenied`` — loud failure
    instead of a silent privileged write. Open scopes (``avatar``/``news``/
    ``chat``/``generic``) and unknown scopes are unaffected — same seam,
    same open/unknown behaviour as the HTTP path. The current only caller
    (the avatar path, an open scope) never needs the flag.

    Raises ``apps.media_files.services.upload_service.UploadValidationError``
    for oversize/wrong-mime/undecodable-image inputs — same contract as
    calling ``upload_file_bytes`` directly; the HTTP view is the one that
    maps that to a 4xx status, not this function.
    """
    require_service("media")
    authorize_scope_write(scope, is_elevated=internal_authorized)

    result = upload_file_bytes(
        data=data,
        declared_mime=mime,
        original_filename=filename,
        scope=scope,
        requested_is_public=None,
        owner_id=owner_id,
        folder=folder,
    )
    meta = result.meta

    audit.record_action(
        None,
        user_id=owner_id,
        action="file_uploaded",
        resource_type="FileMetadata",
        resource_id=str(meta.id),
        changes={
            "path": meta.path,
            "size": meta.size,
            "mime": meta.mime,
            "kind": meta.kind,
            "scope": meta.scope,
            "sha256": meta.sha256,
            "is_public": meta.is_public,
            "via": "interface.store_file",
        },
    )

    if result.enqueue_variants:
        # Fire-and-forget, same precedent as views.upload_file's .delay()
        # call: the FileMetadata row is already committed above, so a
        # broker hiccup (or, under CELERY_TASK_ALWAYS_EAGER, the task
        # itself raising) must not turn an already-saved upload into an
        # exception the caller wasn't expecting from a "store a file" call.
        from apps.media_files.tasks import make_variants

        try:
            make_variants.delay(str(meta.id))
        except Exception:
            logger.exception("make_variants enqueue/run failed for id=%s", meta.id)

    return serialize_file(meta).model_dump(mode="json")


def copy_file(file_id, *, scope: str, folder: str | None = None,
              owner_id: int | None = None, internal_authorized: bool = False) -> dict:
    """Копия уже сохранённого файла в другом scope — тем же пайплайном, что
    ``store_file`` (проверки scope, сигнатура, раскладка по папке, аудит).

    Нужна переносу старых вложений в файловую подсистему (``apps.files``):
    новый scope может быть строже старого (``file_object`` —
    ``owner_gated``, папка на владельца), поэтому байты проходят его
    проверки заново, а не переписываются ключом. Исходная строка не
    трогается — удалять оригинал решает вызывающий.

    Возвращает то же, что ``store_file``, плюс ``source`` — паспорт
    оригинала (``id``, ``owner_id``, ``created_at``, ``sha256``): тому, кто
    переносит, нужно сохранить, КТО и КОГДА загрузил файл на самом деле.
    ``LookupError`` — исходного файла нет (неизвестный id, soft-deleted);
    ``UploadValidationError`` — новый scope файл не принял.
    """
    require_service("media")

    try:
        key = uuid.UUID(str(file_id))
    except (ValueError, AttributeError, TypeError):
        raise LookupError(f"файл {file_id!r} не найден в media") from None
    meta = FileMetadata.objects.filter(pk=key, deleted_at__isnull=True).first()
    if meta is None:
        raise LookupError(f"файл {file_id!r} не найден в media")

    stored = store_file(
        data=read_original(meta), filename=meta.original_filename, mime=meta.mime,
        scope=scope, owner_id=owner_id if owner_id is not None else meta.owner_id,
        internal_authorized=internal_authorized, folder=folder,
    )
    return {**stored, "source": {
        "id": str(meta.pk),
        "owner_id": meta.owner_id,
        "created_at": meta.created_at.isoformat(),
        "sha256": meta.sha256,
    }}


def get_file_url(file_id, variant: str = "original") -> str | None:
    """The URL a caller should hand to a browser for ``file_id`` — signed
    for private files, plain for public ones (see
    ``services.url_service.build_file_url``, which this reuses). ``None``
    if ``file_id`` doesn't resolve to any (non-soft-deleted) row, including
    a malformed/non-UUID id.

    ``variant`` defaults to ``"original"``; pass e.g. ``"thumb_96"`` for a
    derived rendition's URL — same signed-vs-plain rule applies, scoped to
    that variant (a signature minted for one variant never verifies for
    another, see ``build_file_url``). This does not check whether the
    variant has actually been produced yet — same "may 404 until the
    worker runs" contract as the HTTP sign endpoint.
    """
    require_service("media")

    try:
        key = uuid.UUID(str(file_id))
    except (ValueError, AttributeError, TypeError):
        return None

    meta = FileMetadata.objects.filter(pk=key, deleted_at__isnull=True).first()
    if meta is None:
        return None

    url, _exp = build_file_url(meta, variant=variant)
    return url


def get_file_links(file_ids) -> dict[str, dict]:
    """``get_file_url`` для пачки id одним запросом и со сроком жизни:
    ``{id: {"url", "exp"}}``. Id, не разрешившиеся в живую строку
    (неизвестные, кривые, soft-deleted), в ответ не попадают — тот же
    контракт, что ``None`` у одиночной версии.

    ``exp`` — unix-время, после которого подпись не примут (у публичного
    файла — лишь подсказка для кэша, см. ``build_file_url``). Нужен тому, кто отдаёт ссылку
    наружу как «временную» (ТЗ §21, ``DownloadFile``) и должен сказать
    клиенту, до какого момента она действует.
    """
    require_service("media")

    keys: list[uuid.UUID] = []
    for file_id in file_ids:
        try:
            keys.append(uuid.UUID(str(file_id)))
        except (ValueError, AttributeError, TypeError):
            continue
    if not keys:
        return {}

    links: dict[str, dict] = {}
    for meta in FileMetadata.objects.filter(pk__in=keys, deleted_at__isnull=True):
        url, exp = build_file_url(meta, variant="original")
        links[str(meta.pk)] = {"url": url, "exp": exp}
    return links


def get_file_meta(file_id) -> dict | None:
    """Паспорт файла для соседа: имя, тип, размер. ``None``, если id не
    разрешается в живую (не soft-deleted) строку, включая кривой/не-UUID id
    — тот же контракт, что и у ``get_file_url``.

    Нужен тем, кто ПОКАЗЫВАЕТ файл, а не только отдаёт ссылку: чтобы выбрать
    способ показа (PDF во фрейм, картинку в img), надо знать mime, а чтобы
    подписать кнопку — имя и размер. Без этой функции сосед либо гадал бы по
    расширению в URL, либо лез бы в чужую модель напрямую.

    Возвращает простой dict, а не ORM-объект, — как и все функции здесь.
    """
    require_service("media")

    try:
        key = uuid.UUID(str(file_id))
    except (ValueError, AttributeError, TypeError):
        return None

    meta = FileMetadata.objects.filter(pk=key, deleted_at__isnull=True).first()
    if meta is None:
        return None

    return {
        "id": str(meta.pk),
        "filename": meta.original_filename,
        "mime": meta.mime,
        "size": meta.size,
        "kind": meta.kind,
        # Кто и когда загрузил — тому, кто переносит файл в другое место и
        # обязан сохранить его историю (перенос сканов в apps.files).
        "owner_id": meta.owner_id,
        "created_at": meta.created_at.isoformat(),
    }


def delete_file(file_id) -> bool:
    """Best-effort soft-delete of a ``FileMetadata`` row on behalf of a
    neighbour app (currently: ``apps.users.services.profile_service.
    delete_avatar_object``, once avatars became real ``FileMetadata`` rows
    — final review of phases 2-3, Findings 1/2).

    Sets ``deleted_at`` (same soft-delete every serving/list endpoint
    already respects via ``deleted_at__isnull=True``) rather than a hard
    DELETE — consistent with the rest of this app, no S3 object removal
    here (mirrors ``apps.media_files.views``'s deliberate scope: full
    delete/update is a later task, out of scope for 3.3).

    Returns ``True`` if a live (not already soft-deleted) row was found and
    marked deleted, ``False`` for an unknown/malformed/already-deleted id —
    never raises for those cases, only for ``ServiceDisabled``.
    """
    require_service("media")

    try:
        key = uuid.UUID(str(file_id))
    except (ValueError, AttributeError, TypeError):
        return False

    updated = FileMetadata.objects.filter(
        pk=key, deleted_at__isnull=True,
    ).update(deleted_at=timezone.now())
    return bool(updated)
