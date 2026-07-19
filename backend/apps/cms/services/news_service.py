"""Domain logic for News CRUD — kept out of ``views.py``.

Ported from ``services/cms/app/api/v1/news.py`` (the FastAPI route bodies,
minus the routing/HTTP-status concerns, which stay in ``views.py``).

Status side effects vs. the DB trigger
---------------------------------------
Migration ``0002_news_sync_published_trigger`` installs a Postgres trigger
(``cms_news_sync_published``, fires ``BEFORE INSERT OR UPDATE OF status`` on
``cms_news``) that recomputes ``published``/``published_at`` from ``status``
directly in the database. ``apply_status_side_effects`` below computes the
*same* values in Python before every save — this does not fight the trigger,
it duplicates it deliberately, for the same reason the FastAPI original did
(see its docstring): the ORM object handed back to the view/serializer
reflects the correct values immediately, without needing a round trip. The
trigger is still what actually lands in the row; ``News.save()`` is always
called without an ``update_fields`` restriction here (unlike
``contact_requests_service``) specifically so ``status`` is always part of
the UPDATE's column list and the trigger reliably fires. One thing the
trigger does NOT do that Python must: clear ``scheduled_at`` when a post
transitions to ``published`` — that's real, additional logic, not a
duplicate of the trigger.
"""

from __future__ import annotations

from typing import Any, Optional

from django.core.exceptions import SuspiciousOperation
from django.db import transaction
from django.db.models import F, Q
from django.db.utils import IntegrityError
from django.http import Http404
from django.utils import timezone

from apps.cms.models import News, NewsStatus, Tag


class ConflictError(Exception):
    """Raised on a unique-constraint violation (slug conflicts)."""

    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(detail)


def _is_admin(user: Optional[Any]) -> bool:
    return bool(user and getattr(user, "is_admin", False))


def public_visibility_q() -> Q:
    """Filter for what anonymous / non-admin readers may see.

    Published items are always visible. Scheduled items become visible once
    their ``scheduled_at`` is in the past — the lazy auto-publish path.
    Drafts and archived items are never visible to the public.
    """
    now = timezone.now()
    return Q(status=NewsStatus.PUBLISHED) | Q(status=NewsStatus.SCHEDULED, scheduled_at__lte=now)


def _is_publicly_visible(news: News) -> bool:
    now = timezone.now()
    return news.status == NewsStatus.PUBLISHED or (
        news.status == NewsStatus.SCHEDULED
        and news.scheduled_at is not None
        and news.scheduled_at <= now
    )


def apply_status_side_effects(news: News) -> None:
    """Keep ``published``/``published_at``/``scheduled_at`` consistent with
    ``status`` on the in-memory object (see module docstring)."""
    now = timezone.now()
    if news.status == NewsStatus.PUBLISHED:
        news.published = True
        if not news.published_at:
            news.published_at = now
        news.scheduled_at = None
    elif news.status == NewsStatus.SCHEDULED:
        news.published = False
        news.published_at = None
    else:  # draft / archived
        news.published = False
        news.published_at = None


def resolve_tags(tag_ids: list[int]) -> list[Tag]:
    if not tag_ids:
        return []
    tags = list(Tag.objects.filter(id__in=tag_ids))
    found = {t.id for t in tags}
    missing = [tid for tid in tag_ids if tid not in found]
    if missing:
        raise SuspiciousOperation(f"Unknown tag ids: {missing}")
    return tags


def serialize_news(news: News) -> dict[str, Any]:
    """Build the plain dict ``schemas.NewsRead`` validates from.

    Deliberately NOT ``NewsRead.model_validate(news, from_attributes=True)``:
    ``news.tags`` is a Django M2M *manager*, not an iterable of ``Tag``
    (needs ``.all()``), and ``category`` would collide with the model's own
    legacy string column of the same name (see ``schemas.py``'s ``NewsRead``
    docstring) — so the dict is assembled explicitly instead.

    Note ``"category_id"`` (the public field name, matching the FastAPI
    contract) reads Django's ``category_ref_id`` — the model's FK field is
    named ``category_ref`` (not ``category_id``) precisely because
    ``category`` was already taken by the legacy string column, so Django's
    usual ``<field>_id`` convention lands on ``category_ref_id`` here.
    """
    return {
        "id": news.id,
        "title": news.title,
        "slug": news.slug,
        "excerpt": news.excerpt,
        "content": news.content,
        "image": news.image,
        "category_id": news.category_ref_id,
        "author_id": news.author_id,
        "status": news.status,
        "scheduled_at": news.scheduled_at,
        "published": news.published,
        "published_at": news.published_at,
        "created_at": news.created_at,
        "updated_at": news.updated_at,
        "category": news.category_ref,
        "tags": list(news.tags.all()),
        "summary": news.summary,
    }


def _base_queryset():
    return News.objects.select_related("category_ref").prefetch_related("tags")


def list_news(
    *,
    user: Optional[Any],
    category: Optional[str],
    tag: Optional[str],
    status_filter: Optional[NewsStatus],
    q: Optional[str],
    page: int,
    page_size: int,
) -> dict[str, Any]:
    qs = _base_queryset()

    # Visibility gate
    if not _is_admin(user):
        qs = qs.filter(public_visibility_q())
    elif status_filter is not None:
        qs = qs.filter(status=status_filter)

    # Filters
    if category:
        qs = qs.filter(Q(category_ref__slug=category) | Q(category=category))
    if tag:
        qs = qs.filter(tags__slug=tag)
    if q:
        term = q.strip()
        qs = qs.filter(Q(title__icontains=term) | Q(excerpt__icontains=term))

    # Order: scheduled-going-live first (scheduled_at desc), then published_at,
    # then created_at. Postgres's SQL-standard default is NULLS FIRST on a
    # DESC sort — the FastAPI original explicitly overrides that with
    # ``.desc().nullslast()`` so drafts/scheduled rows (published_at IS NULL)
    # don't float to the top of an admin's mixed-status listing;
    # ``nulls_last=True`` here is the same override.
    qs = qs.order_by(
        F("published_at").desc(nulls_last=True),
        F("scheduled_at").desc(nulls_last=True),
        "-created_at",
    )

    total = qs.count()
    offset = (page - 1) * page_size
    rows = list(qs[offset : offset + page_size])
    return {
        "items": [serialize_news(n) for n in rows],
        "page": page,
        "page_size": page_size,
        "total": total,
        "has_next": (page * page_size) < total,
    }


def get_news_by_slug_or_404(slug: str, *, user: Optional[Any]) -> News:
    try:
        news = _base_queryset().get(slug=slug)
    except News.DoesNotExist as exc:
        raise Http404("News not found") from exc
    if not _is_admin(user) and not _is_publicly_visible(news):
        raise Http404("News not found")
    return news


def get_news_or_404(news_id: int, *, user: Optional[Any]) -> News:
    """GET /news/{id} — NOTE: intentionally stricter than the by-slug/list
    visibility gate. The FastAPI original only allows ``PUBLISHED`` here for
    non-admins (not the "scheduled and elapsed" lazy-publish case that
    ``list_news``/``get_news_by_slug_or_404`` allow) — ported verbatim,
    quirk and all, per the task's "match the original exactly" instruction.
    """
    try:
        news = _base_queryset().get(pk=news_id)
    except News.DoesNotExist as exc:
        raise Http404("News not found") from exc
    if not _is_admin(user) and news.status != NewsStatus.PUBLISHED:
        raise Http404("News not found")
    return news


def get_news_for_admin_or_404(news_id: int) -> News:
    """Lookup for the admin-only PATCH/DELETE routes — no visibility gate."""
    try:
        return _base_queryset().get(pk=news_id)
    except News.DoesNotExist as exc:
        raise Http404("News not found") from exc


def create_news(values: dict[str, Any], *, tag_ids: list[int]) -> News:
    model_values = dict(values)
    # See ``serialize_news``'s docstring: the public field is
    # ``category_id``, the Django FK field is ``category_ref`` (so its raw
    # id column is ``category_ref_id``).
    if "category_id" in model_values:
        model_values["category_ref_id"] = model_values.pop("category_id")
    news = News(**model_values)
    tags = resolve_tags(tag_ids)
    apply_status_side_effects(news)
    try:
        with transaction.atomic():
            news.save()
            if tags:
                news.tags.set(tags)
    except IntegrityError as exc:
        raise ConflictError(f"News with slug '{values['slug']}' already exists") from exc
    news.refresh_from_db()
    return news


def update_news(news: News, raw_changes: dict[str, Any]) -> tuple[News, dict[str, Any]]:
    """Apply a partial update. Returns ``(news, applied_changes)`` — the
    latter is what actually landed (after popping ``tag_ids``/``published``
    and deriving ``status`` from the legacy flag), for the caller to log."""
    changes = dict(raw_changes)
    tag_ids = changes.pop("tag_ids", None)
    legacy_published = changes.pop("published", None)
    if legacy_published is not None and "status" not in changes:
        changes["status"] = NewsStatus.PUBLISHED if legacy_published else NewsStatus.DRAFT

    for key, value in changes.items():
        if key == "category_id":
            news.category_ref_id = value
        else:
            setattr(news, key, value)

    tags = resolve_tags(tag_ids) if tag_ids is not None else None
    apply_status_side_effects(news)

    try:
        with transaction.atomic():
            news.save()
            if tags is not None:
                news.tags.set(tags)
    except IntegrityError as exc:
        raise ConflictError("Slug conflict") from exc
    news.refresh_from_db()
    return news, changes


def delete_news(news: News) -> None:
    news.delete()
