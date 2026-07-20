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
from apps.media_files.services.upload_service import upload_file_bytes
from apps.media_files.services.url_service import build_file_url

logger = logging.getLogger(__name__)


def store_file(*, data: bytes, filename: str, mime: str, scope: str,
                owner_id: int | None) -> dict:
    """Run the upload pipeline on behalf of a neighbour app and hand back a
    plain dict shaped like the HTTP upload response
    (``schemas.FileMetadataRead``, at least ``{id, url, mime, size,
    is_public}`` — see that schema for the full field list).

    Raises ``apps.media_files.services.upload_service.UploadValidationError``
    for oversize/wrong-mime/undecodable-image inputs — same contract as
    calling ``upload_file_bytes`` directly; the HTTP view is the one that
    maps that to a 4xx status, not this function.
    """
    require_service("media")

    result = upload_file_bytes(
        data=data,
        declared_mime=mime,
        original_filename=filename,
        scope=scope,
        requested_is_public=None,
        owner_id=owner_id,
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
