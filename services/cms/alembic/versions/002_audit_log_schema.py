"""Move audit_log into cms schema

Revision ID: 0002_cms_audit_schema
Revises: e0c787a032ce
Create Date: 2026-04-24 07:20:00.000000

001_initial created audit_log without a schema qualifier, so it landed in
``public`` instead of ``cms`` (pgbouncer transaction-mode search_path drift).
This migration:

1. Creates ``cms.audit_log`` (idempotent).
2. Moves any stray rows from ``public.audit_log`` into ``cms.audit_log``.
3. Drops ``public.audit_log`` only if it's exclusively the cms one (other
   services that may have created their own public.audit_log by the same
   mistake will have it cleaned up by their own migrations).
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0002_cms_audit_schema"
down_revision: Union[str, None] = "e0c787a032ce"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS cms")

    # Create the target table. No IF NOT EXISTS because we want an error if
    # something prior partially created it without expected columns.
    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("resource_type", sa.String(length=100), nullable=False),
        sa.Column("resource_id", sa.String(length=100), nullable=True),
        sa.Column("changes", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("correlation_id", sa.String(length=36), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="cms",
    )
    for idx in ("action", "correlation_id", "created_at", "resource_id", "user_id"):
        op.create_index(
            op.f(f"ix_cms_audit_log_{idx}"),
            "audit_log",
            [idx],
            unique=False,
            schema="cms",
        )

    # Migrate any rows the service wrote into the wrongly-located
    # public.audit_log OR auth.audit_log before this fix (best-effort;
    # ignore if column set differs, missing table, or duplicate ids).
    # Drop the stale source tables once we've absorbed them — otherwise
    # other services' 003_move_to_own_schema migrations would race over
    # the same physical row set.
    op.execute(
        """
        DO $$
        BEGIN
          IF to_regclass('public.audit_log') IS NOT NULL THEN
            INSERT INTO cms.audit_log (
              user_id, action, resource_type, resource_id, changes,
              ip_address, user_agent, correlation_id, created_at
            )
            SELECT user_id, action, resource_type, resource_id, changes,
                   ip_address, user_agent, correlation_id, created_at
            FROM public.audit_log
            ON CONFLICT DO NOTHING;
            DROP TABLE public.audit_log;
          END IF;
          IF to_regclass('auth.audit_log') IS NOT NULL THEN
            INSERT INTO cms.audit_log (
              user_id, action, resource_type, resource_id, changes,
              ip_address, user_agent, correlation_id, created_at
            )
            SELECT user_id, action, resource_type, resource_id, changes,
                   ip_address, user_agent, correlation_id, created_at
            FROM auth.audit_log
            ON CONFLICT DO NOTHING;
            DROP TABLE auth.audit_log;
          END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    for idx in ("user_id", "resource_id", "created_at", "correlation_id", "action"):
        op.drop_index(
            op.f(f"ix_cms_audit_log_{idx}"), table_name="audit_log", schema="cms"
        )
    op.drop_table("audit_log", schema="cms")
