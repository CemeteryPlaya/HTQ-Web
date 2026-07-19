"""CMS domain models — idiomatic Django, built from scratch in the default
``public`` schema.

Historical note: this app started as a schema-preserving port of the ``cms``
FastAPI microservice (its own ``cms`` Postgres schema, alembic-named
constraints/indexes, a custom ``cms.news_status`` PG enum). The customer
clarified (2026-07-19) that this repo is a standalone copy that never runs
side-by-side with the live FastAPI stack, so there is no reason to preserve
those FastAPI-specific schema details. The models below are plain, idiomatic
Django: default ``public`` schema, Django-generated table/constraint/index
names, and ``TextChoices`` instead of a database enum type.

``db_default=`` is kept on the timestamp/text/bool columns — real DB-level
defaults are a good Django 5.2 idiom (and were a deliberate earlier fix), not
an alembic-parity artifact.

One piece of FastAPI business logic is intentionally preserved: a Postgres
trigger that keeps the legacy ``published``/``published_at`` columns in sync
with ``status`` (see migration ``0002_news_sync_published_trigger``, its
``RunSQL`` operation). Task 1.3 added the News CRUD endpoints
(``apps.cms.services.news_service``) and, per that task's brief, left the
trigger in place rather than folding it into ``save()``/a signal: the
service layer's ``apply_status_side_effects`` computes the same
``published``/``published_at`` values in Python (so the ORM object handed
back to a view reflects the correct values immediately, without a DB round
trip) and always does a full, unrestricted ``News.save()`` so ``status`` is
always part of the UPDATE's column list and the trigger reliably fires too
— the two aren't fighting, they're computing the same thing twice on
purpose. ``scheduled_at`` clearing on publish is the one bit the trigger
does NOT do, and is real (non-duplicate) Python-side logic.
"""

import uuid

from django.db import models
from django.db.models.functions import Now


class NewsStatus(models.TextChoices):
    DRAFT = "draft"
    SCHEDULED = "scheduled"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class Category(models.Model):
    slug = models.CharField(max_length=120, unique=True)
    name = models.CharField(max_length=160)
    description = models.CharField(max_length=500, default="", blank=True, db_default="")
    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Category id={self.id} slug={self.slug!r}>"


class Tag(models.Model):
    slug = models.CharField(max_length=80, unique=True)
    name = models.CharField(max_length=80)
    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Tag id={self.id} slug={self.slug!r}>"


class News(models.Model):
    title = models.CharField(max_length=300)
    slug = models.CharField(max_length=320, unique=True)

    # Editorial
    excerpt = models.CharField(max_length=500, default="", blank=True, db_default="")
    summary = models.TextField(default="", blank=True, db_default="")
    content = models.TextField(default="", blank=True, db_default="")
    image = models.CharField(max_length=500, null=True, blank=True)

    # Taxonomy
    category = models.CharField(max_length=100, default="", blank=True, db_default="", db_index=True)
    # `category_ref` is a ForeignKey — Django already creates an index on FK
    # columns by default, so no redundant `db_index=True` here.
    category_ref = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="news",
    )
    author_id = models.IntegerField(null=True, blank=True, db_index=True)

    # Lifecycle
    status = models.CharField(
        max_length=20, choices=NewsStatus.choices, default=NewsStatus.DRAFT, db_default=NewsStatus.DRAFT,
        db_index=True,
    )
    published = models.BooleanField(default=False, db_default=False, db_index=True)
    published_at = models.DateTimeField(null=True, blank=True, db_index=True)
    scheduled_at = models.DateTimeField(null=True, blank=True, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True, db_default=Now(), db_index=True)
    updated_at = models.DateTimeField(auto_now=True, db_default=Now())

    # A bare M2M — alembic parity (which required an explicit composite-PK
    # through model to avoid a surrogate `id` column) is no longer a goal,
    # so Django is left to manage its own join table normally.
    tags = models.ManyToManyField(Tag, related_name="news_set", blank=True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<News id={self.id} slug={self.slug!r} status={self.status}>"


class ContactRequest(models.Model):
    first_name = models.CharField(max_length=150, default="", blank=True, db_default="")
    last_name = models.CharField(max_length=150, default="", blank=True, db_default="")
    email = models.EmailField(max_length=254)
    message = models.TextField(default="", blank=True, db_default="")
    handled = models.BooleanField(default=False, db_default=False, db_index=True)
    replied_at = models.DateTimeField(null=True, blank=True, db_index=True)
    # FK-less: User lives in a different app/service boundary than cms owns.
    replied_by_id = models.IntegerField(null=True, blank=True)
    reply_message = models.TextField(default="", blank=True, db_default="")
    created_at = models.DateTimeField(auto_now_add=True, db_default=Now(), db_index=True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ContactRequest id={self.id} email={self.email!r} handled={self.handled}>"


class NewsAttachment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    news = models.ForeignKey(News, on_delete=models.CASCADE, related_name="attachments")
    role = models.CharField(max_length=20, default="attachment", blank=True, db_default="attachment")  # attachment | cover
    filename = models.CharField(max_length=255)
    size = models.IntegerField()
    content_type = models.CharField(max_length=255)
    storage_path = models.CharField(max_length=1024)
    uploaded_by = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())


class AuditLog(models.Model):
    user_id = models.IntegerField(null=True, blank=True, db_index=True)
    action = models.CharField(max_length=100, db_index=True)
    resource_type = models.CharField(max_length=100)
    resource_id = models.CharField(max_length=100, null=True, blank=True, db_index=True)
    changes = models.JSONField(null=True, blank=True)
    ip_address = models.CharField(max_length=45, null=True, blank=True)
    user_agent = models.TextField(null=True, blank=True)
    correlation_id = models.CharField(max_length=36, null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True, db_default=Now())
