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
и views.issue_signed_url (через общий views._build_file_url) — никакого
самодельного HMAC здесь, как и предупреждает докстринг
htqweb.storage.signed_url.

Обе функции возвращают только простые dict/str, никогда ORM-объекты
FileMetadata — сосед не должен получить возможность мутировать чужую
модель напрямую.
"""

from __future__ import annotations

import logging
import uuid

from apps.core.services import require_service
from apps.media_files.models import FileMetadata
from apps.media_files.schemas import serialize_file
from apps.media_files.services import audit
from apps.media_files.services.upload_service import upload_file_bytes
from apps.media_files.views import _build_file_url

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


def get_file_url(file_id) -> str | None:
    """The URL a caller should hand to a browser for ``file_id`` — signed
    for private files, plain for public ones (see
    ``views._build_file_url``, which this reuses). ``None`` if ``file_id``
    doesn't resolve to any (non-soft-deleted) row, including a
    malformed/non-UUID id.
    """
    require_service("media")

    try:
        key = uuid.UUID(str(file_id))
    except (ValueError, AttributeError, TypeError):
        return None

    meta = FileMetadata.objects.filter(pk=key, deleted_at__isnull=True).first()
    if meta is None:
        return None

    url, _exp = _build_file_url(meta)
    return url
