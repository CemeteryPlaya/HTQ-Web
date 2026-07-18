"""Move email tables from auth → email schema.

Background: the initial migration (001) was run with a role-level search_path
that put auth first, so CREATE TABLE without a schema qualifier landed in
`auth.*` instead of `email.*`. Env.py now SETs the per-service search_path
at migration time, so any *new* tables go to the right schema. This migration
physically relocates the existing four email tables.

Revision ID: 003
Revises: 2096193f39e5
"""

from alembic import op


revision = "003"
down_revision = "2096193f39e5"
branch_labels = None
depends_on = None


TABLES = [
    "oauth_tokens",
    "email_messages",
    "email_attachments",
    "recipient_statuses",
]


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS email")
    for tbl in TABLES:
        op.execute(
            f"""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema = 'auth' AND table_name = '{tbl}'
                ) AND NOT EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema = 'email' AND table_name = '{tbl}'
                ) THEN
                    EXECUTE 'ALTER TABLE auth.{tbl} SET SCHEMA email';
                END IF;
            END $$;
            """
        )


def downgrade() -> None:
    for tbl in TABLES:
        op.execute(
            f"""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema = 'email' AND table_name = '{tbl}'
                ) THEN
                    EXECUTE 'ALTER TABLE email.{tbl} SET SCHEMA auth';
                END IF;
            END $$;
            """
        )
