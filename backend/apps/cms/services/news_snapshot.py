"""News-content snapshots in S3 — ported from
``services/cms/app/services/news_snapshot.py`` (FastAPI cms-service).

Two files per post live alongside its binary assets in the ``htqweb-cms``
bucket and are kept in sync with the database row:

* ``news/<id>/content.md``    — current published markdown body.
* ``news/<id>/metadata.json`` — fields snapshot (title, slug, summary,
  category, published flag, timestamps, cover_path).

The still-running FastAPI cms-service reads/writes the exact same bucket
during the Strangler Fig transition, so the key layout below
(``news_prefix`` / ``content_object_key`` / ``metadata_object_key``, and the
``content.md`` / ``metadata.json`` names) and ``_serialize``'s field set are
kept BYTE-IDENTICAL to the original — a changed layout would orphan or
shadow objects the other stack depends on.

Async -> sync: the FastAPI original is ``async`` (``await
storage.save(...)``) because it ran under uvicorn as an independently
deployed service; ``htqweb.storage`` (Task 1.6) is sync (Decision Д11 — this
monolith is WSGI-first), so this port drops ``async``/``await`` throughout.

The flow (per the architectural decision in this branch):
* on news create   -> write a snapshot.
* on news update   -> overwrite both files so the bucket always reflects the
  latest published version.
* on news delete   -> drop both files plus cover/attachments under the post
  prefix.

(News create/update/delete views themselves are a later task — Task 1.7
only ports the snapshot service and the background tasks that use it.)
"""

from __future__ import annotations

import json
from typing import Any

from htqweb.storage import Storage, get_storage

from apps.cms.models import News


def news_prefix(news_id: int) -> str:
    return f"news/{news_id}"


def content_object_key(news_id: int) -> str:
    return f"{news_prefix(news_id)}/content.md"


def metadata_object_key(news_id: int) -> str:
    return f"{news_prefix(news_id)}/metadata.json"


def _serialize(news: News) -> dict[str, Any]:
    def dt(value: Any) -> str | None:
        return value.isoformat() if value is not None else None

    return {
        "id": news.id,
        "title": news.title,
        "slug": news.slug,
        "summary": news.summary,
        "category": news.category,
        "image": news.image,
        "published": news.published,
        "published_at": dt(news.published_at),
        "created_at": dt(news.created_at),
    }


def write_news_snapshot(news: News, *, storage: Storage | None = None) -> None:
    """Overwrite ``content.md`` + ``metadata.json`` for the given post."""
    storage = storage or get_storage()
    storage.save(
        content_object_key(news.id),
        (news.content or "").encode("utf-8"),
        content_type="text/markdown; charset=utf-8",
    )
    storage.save(
        metadata_object_key(news.id),
        json.dumps(_serialize(news), ensure_ascii=False, indent=2).encode("utf-8"),
        content_type="application/json",
    )


def delete_news_snapshot(news_id: int, *, storage: Storage | None = None) -> None:
    """Best-effort delete of the snapshot pair. Cover image and attachments
    are dropped by their own routes."""
    storage = storage or get_storage()
    for key in (content_object_key(news_id), metadata_object_key(news_id)):
        try:
            storage.delete(key)
        except Exception:  # noqa: BLE001 — bucket cleanup is non-critical
            pass
