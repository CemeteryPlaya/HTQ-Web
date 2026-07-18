"""Share-link security: token hashing, watermark, audit log.

Revision ID: 007
Revises: 006
Create Date: 2026-05-04

Why:
- Raw tokens in `hr_shareable_links.token` are equivalent to plaintext passwords.
- Anyone with read access to a backup/dump gets working URLs to the org chart.
- Move to SHA-256(token_hash) — raw token is shown to the creator exactly once
  at POST time and never persisted.

Strategy:
1. Add `token_hash` nullable + new fields (viewer_label, watermark_text,
   revoked_at, used_at).
2. Backfill `token_hash` for every existing row using pgcrypto's digest().
3. Promote `token_hash` to NOT NULL UNIQUE; drop the unique constraint on `token`
   so legacy rows can keep their plaintext (read-only) without blocking new
   nullable inserts. The `token` column itself stays for one release window —
   revision 008 will drop it after the longest legacy expires_at has passed.
4. Create append-only `hr_share_link_audit` for every open/denied/revoked event.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # pgcrypto is already loaded in 005; idempotent re-declare just in case.
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    # ── 1. Schema changes on hr_shareable_links ──────────────────────────
    op.add_column(
        "hr_shareable_links",
        sa.Column("token_hash", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "hr_shareable_links",
        sa.Column("viewer_label", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "hr_shareable_links",
        sa.Column("watermark_text", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "hr_shareable_links",
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "hr_shareable_links",
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
    )

    # ── 2. Backfill token_hash for existing rows ─────────────────────────
    op.execute(
        "UPDATE hr_shareable_links "
        "SET token_hash = encode(digest(token, 'sha256'), 'hex') "
        "WHERE token_hash IS NULL AND token IS NOT NULL"
    )
    # Mirror existing is_active=False rows into revoked_at so audit history is
    # consistent for previously-revoked links. used_at gets opened_at where the
    # link was already opened.
    op.execute(
        "UPDATE hr_shareable_links "
        "SET revoked_at = COALESCE(opened_at, created_at, now()) "
        "WHERE is_active = FALSE AND revoked_at IS NULL AND opened_at IS NULL"
    )
    op.execute(
        "UPDATE hr_shareable_links "
        "SET used_at = opened_at "
        "WHERE used_at IS NULL AND opened_at IS NOT NULL"
    )

    # ── 3. Promote token_hash; relax token uniqueness ────────────────────
    op.alter_column("hr_shareable_links", "token_hash", nullable=False)
    op.create_index(
        "ix_shareable_links_token_hash",
        "hr_shareable_links",
        ["token_hash"],
        unique=True,
    )
    # Drop the unique on raw token. Keep the column NULLABLE for now so future
    # rows can store NULL. The column itself is dropped in a later migration
    # after the longest expires_at has passed (deprecation window).
    op.drop_index("ix_shareable_links_token", table_name="hr_shareable_links")
    op.alter_column("hr_shareable_links", "token", nullable=True)

    # ── 4. Append-only audit log ─────────────────────────────────────────
    op.create_table(
        "hr_share_link_audit",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "link_id",
            sa.UUID(),
            sa.ForeignKey("hr_shareable_links.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "action",
            sa.String(length=20),
            nullable=False,
        ),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("ip", sa.String(length=45), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("reason", sa.String(length=64), nullable=True),
        sa.CheckConstraint(
            "action IN ('open','denied_revoked','denied_expired','denied_used',"
            "'denied_unknown','revoked','created')",
            name="ck_share_link_audit_action",
        ),
    )
    op.create_index(
        "ix_share_link_audit_link",
        "hr_share_link_audit",
        ["link_id", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_share_link_audit_link", table_name="hr_share_link_audit")
    op.drop_table("hr_share_link_audit")

    op.alter_column("hr_shareable_links", "token", nullable=False)
    op.create_index(
        "ix_shareable_links_token",
        "hr_shareable_links",
        ["token"],
        unique=True,
    )

    op.drop_index("ix_shareable_links_token_hash", table_name="hr_shareable_links")
    op.drop_column("hr_shareable_links", "used_at")
    op.drop_column("hr_shareable_links", "revoked_at")
    op.drop_column("hr_shareable_links", "watermark_text")
    op.drop_column("hr_shareable_links", "viewer_label")
    op.drop_column("hr_shareable_links", "token_hash")
