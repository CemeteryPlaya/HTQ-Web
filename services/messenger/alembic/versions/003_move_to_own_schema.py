"""Move messenger tables from auth → messenger schema.

Background: the initial migration (001) was run with a role-level search_path
that put auth first, so CREATE TABLE without a schema qualifier landed in
`auth.*` instead of `messenger.*`. Env.py now SETs the per-service search_path
at migration time, so any *new* tables go to the right schema. This migration
physically relocates the existing six messenger tables.

Safe to run when tables are either in `auth` (current prod-like state) or
already in `messenger` (idempotent via IF EXISTS + conditional schema check).

Revision ID: 003
Revises: cfd9da4d596b
"""

from alembic import op


revision = "003"
down_revision = "cfd9da4d596b"
branch_labels = None
depends_on = None


TABLES = [
    "chat_user_replicas",
    "rooms",
    "room_participants",
    "messages",
    "chat_attachments",
    "user_keys",
]


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS messenger")
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
                    WHERE table_schema = 'messenger' AND table_name = '{tbl}'
                ) THEN
                    EXECUTE 'ALTER TABLE auth.{tbl} SET SCHEMA messenger';
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
                    WHERE table_schema = 'messenger' AND table_name = '{tbl}'
                ) THEN
                    EXECUTE 'ALTER TABLE messenger.{tbl} SET SCHEMA auth';
                END IF;
            END $$;
            """
        )
