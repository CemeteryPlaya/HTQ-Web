"""News taxonomy: tags, categories, status, scheduling, author, excerpt.

Revision ID: 0004_news_taxonomy
Revises: 0003_news_attachments
Create Date: 2026-05-07 00:00:00.000000

Extends ``cms.news`` with metadata fields the editorial UI needs (tags,
category FK, author, status enum, scheduled publication, updated_at).
Adds ``cms.tags``, ``cms.categories`` and the ``cms.news_tags`` join table.

The legacy ``published`` boolean is kept for one release as a denormalized
mirror of ``status='published'`` so that any caller still reading it does not
break; the API now writes to ``status`` and the boolean is updated in lockstep
through a trigger. Legacy ``category`` string column is kept too — old rows
without a ``category_id`` fall back to it.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0004_news_taxonomy"
down_revision: Union[str, None] = "0003_news_attachments"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enum --------------------------------------------------------------
    news_status = sa.Enum(
        "draft", "scheduled", "published", "archived",
        name="news_status",
        schema="cms",
    )
    news_status.create(op.get_bind(), checkfirst=True)

    # Categories --------------------------------------------------------
    op.create_table(
        "categories",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("slug", sa.String(length=120), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.String(length=500), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("slug", name="uq_cms_categories_slug"),
        schema="cms",
    )
    op.create_index("ix_cms_categories_slug", "categories", ["slug"], schema="cms")

    # Tags --------------------------------------------------------------
    op.create_table(
        "tags",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("slug", name="uq_cms_tags_slug"),
        schema="cms",
    )
    op.create_index("ix_cms_tags_slug", "tags", ["slug"], schema="cms")

    # News table extensions --------------------------------------------
    op.add_column(
        "news",
        sa.Column("excerpt", sa.String(length=500), server_default="", nullable=False),
        schema="cms",
    )
    op.add_column(
        "news",
        sa.Column(
            "status",
            sa.Enum(
                "draft", "scheduled", "published", "archived",
                name="news_status", schema="cms",
                create_type=False,
            ),
            server_default="draft",
            nullable=False,
        ),
        schema="cms",
    )
    op.add_column(
        "news",
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        schema="cms",
    )
    op.add_column(
        "news",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        schema="cms",
    )
    op.add_column(
        "news",
        sa.Column("category_id", sa.Integer(), nullable=True),
        schema="cms",
    )
    op.add_column(
        "news",
        sa.Column("author_id", sa.Integer(), nullable=True),
        schema="cms",
    )
    op.create_foreign_key(
        "fk_cms_news_category",
        "news", "categories",
        ["category_id"], ["id"],
        source_schema="cms", referent_schema="cms",
        ondelete="SET NULL",
    )
    op.create_index("ix_cms_news_status", "news", ["status"], schema="cms")
    op.create_index("ix_cms_news_scheduled_at", "news", ["scheduled_at"], schema="cms")
    op.create_index("ix_cms_news_category_id", "news", ["category_id"], schema="cms")
    op.create_index("ix_cms_news_author_id", "news", ["author_id"], schema="cms")

    # Backfill: status from legacy boolean, excerpt from summary.
    op.execute(
        """
        UPDATE cms.news
        SET status = CASE WHEN published THEN 'published'::cms.news_status
                          ELSE 'draft'::cms.news_status END,
            excerpt = COALESCE(NULLIF(summary, ''), LEFT(content, 280))
        """
    )

    # Trigger keeps legacy `published` mirror in sync with status.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION cms._news_sync_published() RETURNS TRIGGER AS $$
        BEGIN
            NEW.published := (NEW.status = 'published');
            IF NEW.status = 'published' AND NEW.published_at IS NULL THEN
                NEW.published_at := now();
            ELSIF NEW.status <> 'published' THEN
                NEW.published_at := NULL;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute("DROP TRIGGER IF EXISTS news_sync_published ON cms.news")
    op.execute(
        """
        CREATE TRIGGER news_sync_published
        BEFORE INSERT OR UPDATE OF status ON cms.news
        FOR EACH ROW EXECUTE FUNCTION cms._news_sync_published()
        """
    )

    # Join table -------------------------------------------------------
    op.create_table(
        "news_tags",
        sa.Column("news_id", sa.Integer(), nullable=False),
        sa.Column("tag_id", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("news_id", "tag_id"),
        sa.ForeignKeyConstraint(
            ["news_id"], ["cms.news.id"], ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tag_id"], ["cms.tags.id"], ondelete="CASCADE",
        ),
        schema="cms",
    )
    op.create_index("ix_cms_news_tags_tag_id", "news_tags", ["tag_id"], schema="cms")


def downgrade() -> None:
    op.drop_index("ix_cms_news_tags_tag_id", table_name="news_tags", schema="cms")
    op.drop_table("news_tags", schema="cms")

    op.execute("DROP TRIGGER IF EXISTS news_sync_published ON cms.news")
    op.execute("DROP FUNCTION IF EXISTS cms._news_sync_published()")

    op.drop_index("ix_cms_news_author_id", table_name="news", schema="cms")
    op.drop_index("ix_cms_news_category_id", table_name="news", schema="cms")
    op.drop_index("ix_cms_news_scheduled_at", table_name="news", schema="cms")
    op.drop_index("ix_cms_news_status", table_name="news", schema="cms")
    op.drop_constraint("fk_cms_news_category", "news", type_="foreignkey", schema="cms")
    op.drop_column("news", "author_id", schema="cms")
    op.drop_column("news", "category_id", schema="cms")
    op.drop_column("news", "updated_at", schema="cms")
    op.drop_column("news", "scheduled_at", schema="cms")
    op.drop_column("news", "status", schema="cms")
    op.drop_column("news", "excerpt", schema="cms")

    op.drop_index("ix_cms_tags_slug", table_name="tags", schema="cms")
    op.drop_table("tags", schema="cms")
    op.drop_index("ix_cms_categories_slug", table_name="categories", schema="cms")
    op.drop_table("categories", schema="cms")

    sa.Enum(name="news_status", schema="cms").drop(op.get_bind(), checkfirst=True)
