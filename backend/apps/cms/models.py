"""CMS domain models — Django port of the ``cms`` FastAPI microservice.

Schema verification (Task 1.1, Step 1) — extracted from
``services/cms/app/core/settings.py`` (``db_schema``), the alembic chain
(``services/cms/alembic/versions/001_initial.py`` .. ``004_news_taxonomy.py``)
and the SQLAlchemy models (``services/cms/app/models/*.py``). Recorded here so
the Django migration (Step 4) can be reviewed against it without re-reading
five source files.

Schema: ``cms`` (confirmed — ``Settings.db_schema = "cms"``).

Tables (final state, after all four alembic revisions are folded together).
All integer PKs are plain ``Integer``/``serial`` (alembic's ``sa.Integer()``),
NOT Django's default ``BigAutoField`` — every model below declares ``id``
explicitly as ``AutoField`` to keep the column type ``integer``, not
``bigint``, matching alembic exactly.

- ``cms.news`` — id PK autoincrement (int4); title varchar(300) NOT NULL;
  slug varchar(320) NOT NULL, UNIQUE via a *plain unique index*
  ``ix_cms_news_slug`` (alembic used ``create_index(..., unique=True)``, not a
  named table constraint — replicated here as a ``UniqueConstraint`` named
  identically, which is the closest Django idiom and produces a real
  postgres index of that exact name); excerpt varchar(500) NOT NULL DEFAULT
  '' (added 004); summary text NOT NULL DEFAULT ''; content text NOT NULL
  DEFAULT ''; image varchar(500) NULL; category varchar(100) NOT NULL
  DEFAULT '' (ix_cms_news_category); category_id int NULL FK ->
  cms.categories.id ON DELETE SET NULL (ix_cms_news_category_id, added 004);
  author_id int NULL (ix_cms_news_author_id, added 004); status
  cms.news_status NOT NULL DEFAULT 'draft' (ix_cms_news_status, added 004) —
  ``CharField`` on the Python side per the task brief, physical column type
  stays the PG enum (converted via RunSQL right after CreateModel, see the
  migration); published boolean NOT NULL DEFAULT false (ix_cms_news_published);
  published_at timestamptz NULL (ix_cms_news_published_at); scheduled_at
  timestamptz NULL (ix_cms_news_scheduled_at, added 004); created_at
  timestamptz NOT NULL DEFAULT now() (ix_cms_news_created_at); updated_at
  timestamptz NOT NULL DEFAULT now() (added 004, NO index — confirmed absent
  from alembic's create_index calls).
  A DB trigger (``cms._news_sync_published`` / ``news_sync_published``,
  added 004) keeps the legacy ``published`` boolean and ``published_at`` in
  sync with ``status`` on INSERT/UPDATE OF status — ported verbatim via
  RunSQL so behaviour parity holds, not just column parity.

- ``cms.contact_requests`` — id PK (int4); first_name varchar(150) NOT NULL
  DEFAULT ''; last_name varchar(150) NOT NULL DEFAULT ''; email varchar(254)
  NOT NULL; message text NOT NULL DEFAULT ''; handled boolean NOT NULL
  DEFAULT false (ix_cms_contact_requests_handled); replied_at timestamptz
  NULL (ix_cms_contact_requests_replied_at); replied_by_id int NULL (no FK —
  User lives in the ``auth`` schema owned by user-service); reply_message
  text NOT NULL DEFAULT ''; created_at timestamptz NOT NULL DEFAULT now()
  (ix_cms_contact_requests_created_at).

- ``cms.categories`` (added 004) — id PK (int4); slug varchar(120) NOT NULL,
  UNIQUE via a named constraint ``uq_cms_categories_slug`` *plus* a separate
  plain (non-unique-by-declaration) index ``ix_cms_categories_slug`` on the
  same column — alembic really does create both objects, replicated as-is;
  name varchar(160) NOT NULL; description varchar(500) NOT NULL DEFAULT '';
  created_at timestamptz NOT NULL DEFAULT now() (no index).

- ``cms.tags`` (added 004) — id PK (int4); slug varchar(80) NOT NULL, same
  UNIQUE-constraint + separate-index pattern (``uq_cms_tags_slug`` +
  ``ix_cms_tags_slug``); name varchar(80) NOT NULL; created_at timestamptz
  NOT NULL DEFAULT now() (no index).

- ``cms.news_attachments`` (added 003) — id UUID PK, Python-side default
  (uuid.uuid4 — the alembic migration does NOT set a server default); news_id
  int NOT NULL FK -> cms.news.id ON DELETE CASCADE (ix_cms_news_attachments_news_id);
  role varchar(20) NOT NULL DEFAULT 'attachment'; filename varchar(255) NOT
  NULL; size int NOT NULL; content_type varchar(255) NOT NULL; storage_path
  varchar(1024) NOT NULL; uploaded_by int NULL; created_at timestamptz NOT
  NULL DEFAULT now().

- ``cms.audit_log`` — 001_initial created this table WITHOUT a schema
  qualifier (a pgbouncer/search_path bug), so it landed in ``public``;
  002_audit_log_schema recreates it under ``cms`` and migrates stray rows.
  Final columns: id PK (int4); user_id int NULL (ix_cms_audit_log_user_id);
  action varchar(100) NOT NULL (ix_cms_audit_log_action); resource_type
  varchar(100) NOT NULL; resource_id varchar(100) NULL
  (ix_cms_audit_log_resource_id); changes JSONB NULL; ip_address varchar(45)
  NULL; user_agent text NULL; correlation_id varchar(36) NULL
  (ix_cms_audit_log_correlation_id); created_at timestamptz NOT NULL
  DEFAULT now() (ix_cms_audit_log_created_at).
  We build straight into ``cms`` from the start — no need to replay the
  public->cms bug on a fresh DB.

- ``cms.news_tags`` (M2M join, added 004) — composite PK (news_id, tag_id),
  NO surrogate ``id`` column; news_id int NOT NULL FK -> cms.news.id ON
  DELETE CASCADE; tag_id int NOT NULL FK -> cms.tags.id ON DELETE CASCADE
  (ix_cms_news_tags_tag_id — tag_id alone, in addition to the composite PK).
  Django's automatic M2M through table always adds a surrogate ``id``, so it
  would NOT be schema-equivalent; modelled explicitly below as ``NewsTag``
  using Django 5.2's ``CompositePrimaryKey``.

PG enum ``cms.news_status`` (added 004, ``sa.Enum("draft", "scheduled",
"published", "archived", name="news_status", schema="cms")``) — NOTE: four
labels, not three; the task brief's illustrative RunSQL snippet
(``'draft','published','archived'``) omits ``scheduled`` and was verified
wrong against the alembic source, so the migration below uses the correct
four-label enum.
"""

import uuid

from django.db import models


class NewsStatus(models.TextChoices):
    DRAFT = "draft"
    SCHEDULED = "scheduled"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class Category(models.Model):
    id = models.AutoField(primary_key=True)
    slug = models.CharField(max_length=120, unique=False)
    name = models.CharField(max_length=160)
    description = models.CharField(max_length=500, default="", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = True
        db_table = 'cms"."categories'
        constraints = [
            models.UniqueConstraint(fields=["slug"], name="uq_cms_categories_slug"),
        ]
        indexes = [
            models.Index(fields=["slug"], name="ix_cms_categories_slug"),
        ]

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Category id={self.id} slug={self.slug!r}>"


class Tag(models.Model):
    id = models.AutoField(primary_key=True)
    slug = models.CharField(max_length=80, unique=False)
    name = models.CharField(max_length=80)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = True
        db_table = 'cms"."tags'
        constraints = [
            models.UniqueConstraint(fields=["slug"], name="uq_cms_tags_slug"),
        ]
        indexes = [
            models.Index(fields=["slug"], name="ix_cms_tags_slug"),
        ]

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Tag id={self.id} slug={self.slug!r}>"


class News(models.Model):
    id = models.AutoField(primary_key=True)
    title = models.CharField(max_length=300)
    slug = models.CharField(max_length=320, unique=False, db_index=False)

    # Editorial
    excerpt = models.CharField(max_length=500, default="", blank=True)
    summary = models.TextField(default="", blank=True)
    content = models.TextField(default="", blank=True)
    image = models.CharField(max_length=500, null=True, blank=True)

    # Taxonomy
    category = models.CharField(max_length=100, default="", blank=True, db_index=False)
    # db_constraint=False: Django's on_delete is application-side only and
    # would otherwise create the FK with an implicit NO ACTION at the DB
    # level (confdeltype='a'), not the real ON DELETE SET NULL alembic has
    # (fk_cms_news_category). The matching RunSQL in the migration adds the
    # actual constraint with that exact name and ON DELETE clause.
    category_ref = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column="category_id",
        db_index=False,
        db_constraint=False,
        related_name="news",
    )
    author_id = models.IntegerField(null=True, blank=True, db_index=False)

    # Lifecycle — CharField on the Python side (task brief decision); the
    # physical DB column type stays the `cms.news_status` PG enum created by
    # the migration (RunSQL ALTER COLUMN right after CreateModel).
    status = models.CharField(
        max_length=20, choices=NewsStatus.choices, default=NewsStatus.DRAFT, db_index=False,
    )
    published = models.BooleanField(default=False, db_index=False)
    published_at = models.DateTimeField(null=True, blank=True, db_index=False)
    scheduled_at = models.DateTimeField(null=True, blank=True, db_index=False)

    created_at = models.DateTimeField(auto_now_add=True, db_index=False)
    updated_at = models.DateTimeField(auto_now=True)

    tags = models.ManyToManyField(Tag, through="NewsTag", related_name="news_set")

    class Meta:
        managed = True
        db_table = 'cms"."news'
        constraints = [
            models.UniqueConstraint(fields=["slug"], name="ix_cms_news_slug"),
        ]
        indexes = [
            models.Index(fields=["category"], name="ix_cms_news_category"),
            models.Index(fields=["created_at"], name="ix_cms_news_created_at"),
            models.Index(fields=["published"], name="ix_cms_news_published"),
            models.Index(fields=["published_at"], name="ix_cms_news_published_at"),
            models.Index(fields=["status"], name="ix_cms_news_status"),
            models.Index(fields=["scheduled_at"], name="ix_cms_news_scheduled_at"),
            models.Index(fields=["category_ref"], name="ix_cms_news_category_id"),
            models.Index(fields=["author_id"], name="ix_cms_news_author_id"),
        ]

    def __repr__(self) -> str:  # pragma: no cover
        return f"<News id={self.id} slug={self.slug!r} status={self.status}>"


class NewsTag(models.Model):
    """Explicit through model for ``cms.news_tags`` — composite PK, no
    surrogate ``id`` column, to stay schema-equivalent with the alembic
    ``news_tags`` join table."""

    # db_constraint=False on both: see the News.category_ref comment — real
    # ON DELETE CASCADE is added via RunSQL in the migration instead of
    # relying on Django's (application-side-only) on_delete.
    pk = models.CompositePrimaryKey("news_id", "tag_id")
    # db_index=False on news_id: alembic has no standalone index there — it's
    # already the leading column of the composite PK index, so a separate
    # one (Django's FK default) would be an extra, unlisted-in-alembic index.
    news = models.ForeignKey(
        News, on_delete=models.CASCADE, db_column="news_id", db_index=False, db_constraint=False,
    )
    tag = models.ForeignKey(Tag, on_delete=models.CASCADE, db_column="tag_id", db_index=False, db_constraint=False)

    class Meta:
        managed = True
        db_table = 'cms"."news_tags'
        indexes = [
            models.Index(fields=["tag"], name="ix_cms_news_tags_tag_id"),
        ]


class ContactRequest(models.Model):
    id = models.AutoField(primary_key=True)
    first_name = models.CharField(max_length=150, default="", blank=True)
    last_name = models.CharField(max_length=150, default="", blank=True)
    email = models.EmailField(max_length=254)
    message = models.TextField(default="", blank=True)
    handled = models.BooleanField(default=False, db_index=False)
    replied_at = models.DateTimeField(null=True, blank=True, db_index=False)
    # FK-less: User lives in the `auth` schema, owned by user-service.
    replied_by_id = models.IntegerField(null=True, blank=True)
    reply_message = models.TextField(default="", blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=False)

    class Meta:
        managed = True
        db_table = 'cms"."contact_requests'
        # NOTE: ix_cms_contact_requests_created_at / _handled / _replied_at are
        # all >30 chars — Django's Index name validation (models.E034) caps
        # custom index names at 30 (a cross-DB-portability rule, not a real
        # Postgres limit), so these three are created via RunSQL in the
        # migration instead of declared here.

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ContactRequest id={self.id} email={self.email!r} handled={self.handled}>"


class NewsAttachment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # db_constraint=False: see the News.category_ref comment — real ON
    # DELETE CASCADE is added via RunSQL in the migration.
    news = models.ForeignKey(
        News, on_delete=models.CASCADE, db_column="news_id", db_index=False,
        db_constraint=False, related_name="attachments",
    )
    role = models.CharField(max_length=20, default="attachment", blank=True)  # attachment | cover
    filename = models.CharField(max_length=255)
    size = models.IntegerField()
    content_type = models.CharField(max_length=255)
    storage_path = models.CharField(max_length=1024)
    uploaded_by = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = True
        db_table = 'cms"."news_attachments'
        # ix_cms_news_attachments_news_id is 31 chars — over Django's Index
        # name cap (models.E034); created via RunSQL in the migration instead.


class AuditLog(models.Model):
    id = models.AutoField(primary_key=True)
    user_id = models.IntegerField(null=True, blank=True, db_index=False)
    action = models.CharField(max_length=100, db_index=False)
    resource_type = models.CharField(max_length=100)
    resource_id = models.CharField(max_length=100, null=True, blank=True, db_index=False)
    changes = models.JSONField(null=True, blank=True)
    ip_address = models.CharField(max_length=45, null=True, blank=True)
    user_agent = models.TextField(null=True, blank=True)
    correlation_id = models.CharField(max_length=36, null=True, blank=True, db_index=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=False)

    class Meta:
        managed = True
        db_table = 'cms"."audit_log'
        indexes = [
            models.Index(fields=["user_id"], name="ix_cms_audit_log_user_id"),
            models.Index(fields=["action"], name="ix_cms_audit_log_action"),
            models.Index(fields=["resource_id"], name="ix_cms_audit_log_resource_id"),
            models.Index(fields=["created_at"], name="ix_cms_audit_log_created_at"),
        ]
        # ix_cms_audit_log_correlation_id is 31 chars — over Django's Index
        # name cap (models.E034); created via RunSQL in the migration instead.
