"""Create messenger audit log table.

Revision ID: 005_create_audit_log
Revises: 004_chat_storage
"""

from __future__ import annotations

from alembic import op

from app.core.settings import settings


revision = "005_create_audit_log"
down_revision = "004_chat_storage"
branch_labels = None
depends_on = None

SCHEMA = settings.db_schema


def upgrade() -> None:
    op.execute(f'CREATE SCHEMA IF NOT EXISTS "{SCHEMA}"')
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = 'audit_log'
            ) AND NOT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = '{SCHEMA}' AND table_name = 'audit_log'
            ) THEN
                EXECUTE 'ALTER TABLE public.audit_log SET SCHEMA {SCHEMA}';
            ELSIF EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'auth' AND table_name = 'audit_log'
            ) AND NOT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = '{SCHEMA}' AND table_name = 'audit_log'
            ) THEN
                EXECUTE 'ALTER TABLE auth.audit_log SET SCHEMA {SCHEMA}';
            END IF;
        END $$;
        """
    )
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS "{SCHEMA}"."audit_log" (
            id SERIAL PRIMARY KEY,
            user_id INTEGER,
            action VARCHAR(100) NOT NULL,
            resource_type VARCHAR(100) NOT NULL,
            resource_id VARCHAR(100),
            changes JSONB,
            ip_address VARCHAR(45),
            user_agent TEXT,
            correlation_id VARCHAR(36),
            created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL
        )
        """
    )
    op.execute(f'CREATE INDEX IF NOT EXISTS "ix_audit_log_action" ON "{SCHEMA}"."audit_log" (action)')
    op.execute(f'CREATE INDEX IF NOT EXISTS "ix_audit_log_created_at" ON "{SCHEMA}"."audit_log" (created_at)')
    op.execute(f'CREATE INDEX IF NOT EXISTS "ix_audit_log_correlation_id" ON "{SCHEMA}"."audit_log" (correlation_id)')
    op.execute(f'CREATE INDEX IF NOT EXISTS "ix_audit_log_resource_id" ON "{SCHEMA}"."audit_log" (resource_id)')
    op.execute(f'CREATE INDEX IF NOT EXISTS "ix_audit_log_user_id" ON "{SCHEMA}"."audit_log" (user_id)')


def downgrade() -> None:
    op.execute(f'DROP TABLE IF EXISTS "{SCHEMA}"."audit_log"')
