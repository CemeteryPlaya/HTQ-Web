"""Unified email_accounts table + EmailMessage FK switch.

Adds a single ``email.email_accounts`` row per user-owned mailbox or OAuth
identity, so the frontend can list them with one query and switch between
corporate (Mailcow) and personal (Gmail/Outlook) accounts as if they were
tabs. Existing ``provisioned_mailboxes`` and ``oauth_tokens`` rows are
backfilled into ``email_accounts``; ``email_messages.account_id`` is
re-pointed from ``oauth_tokens`` to the new table.

Revision ID: 005_email_accounts
Revises: 004_provisioned_mailboxes
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "005_email_accounts"
down_revision = "004_provisioned_mailboxes"
branch_labels = None
depends_on = None


SCHEMA = "email"


# Tables that *should* live in the `email` schema after migration 003 but
# may still be in `public` if the original `auth` → `email` SET SCHEMA was
# a no-op (the tables had landed in `public` from day one). Repair before
# anything else touches them.
_LEGACY_TABLES = ("oauth_tokens", "email_messages", "email_attachments", "recipient_statuses")


def _repair_legacy_schema() -> None:
    """Move email tables from `public` into the `email` schema if needed."""
    op.execute("CREATE SCHEMA IF NOT EXISTS email")
    for tbl in _LEGACY_TABLES:
        op.execute(
            f"""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.tables
                     WHERE table_schema = 'public' AND table_name = '{tbl}'
                ) AND NOT EXISTS (
                    SELECT 1 FROM information_schema.tables
                     WHERE table_schema = 'email' AND table_name = '{tbl}'
                ) THEN
                    EXECUTE 'ALTER TABLE public.{tbl} SET SCHEMA email';
                END IF;
            END $$;
            """
        )


def upgrade() -> None:
    # 0. Repair: ensure oauth_tokens and friends live in `email` schema
    _repair_legacy_schema()

    # 1. Create email_accounts
    op.create_table(
        "email_accounts",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("address", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("mailbox_id", sa.Integer(), nullable=True),
        sa.Column("oauth_token_id", sa.Integer(), nullable=True),
        sa.Column(
            "sync_state",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_error", sa.Text(), nullable=True),
        sa.Column("watch_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "connected_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["mailbox_id"],
            ["email.provisioned_mailboxes.id"],
            ondelete="SET NULL",
            name="fk_email_accounts_mailbox_id",
        ),
        sa.ForeignKeyConstraint(
            ["oauth_token_id"],
            ["email.oauth_tokens.id"],
            ondelete="SET NULL",
            name="fk_email_accounts_oauth_token_id",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "address", name="uq_email_accounts_user_address"),
        sa.UniqueConstraint("mailbox_id", name="uq_email_accounts_mailbox_id"),
        sa.UniqueConstraint("oauth_token_id", name="uq_email_accounts_oauth_token_id"),
        sa.CheckConstraint(
            "type IN ('corporate','personal')",
            name="ck_email_accounts_type",
        ),
        sa.CheckConstraint(
            "provider IN ('mailcow','google','microsoft')",
            name="ck_email_accounts_provider",
        ),
        sa.CheckConstraint(
            "(type = 'corporate' AND mailbox_id IS NOT NULL AND oauth_token_id IS NULL) "
            "OR (type = 'personal' AND oauth_token_id IS NOT NULL AND mailbox_id IS NULL)",
            name="ck_email_accounts_type_consistency",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_email_accounts_user_id",
        "email_accounts",
        ["user_id"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_email_accounts_user_active",
        "email_accounts",
        ["user_id", "is_active"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_email_accounts_watch_expires_at",
        "email_accounts",
        ["watch_expires_at"],
        schema=SCHEMA,
    )
    # Partial unique: at most one default account per user
    op.execute(
        "CREATE UNIQUE INDEX ux_email_accounts_default_per_user "
        "ON email.email_accounts (user_id) WHERE is_default"
    )

    # 2. Backfill from corporate mailboxes (active or archived)
    op.execute(
        """
        INSERT INTO email.email_accounts
            (user_id, type, provider, address, display_name,
             is_active, is_default, mailbox_id,
             sync_state, connected_at, created_at, updated_at)
        SELECT
            user_id,
            'corporate',
            'mailcow',
            address,
            display_name,
            (status = 'active'),
            false,
            id,
            '{}'::jsonb,
            created_at,
            created_at,
            updated_at
          FROM email.provisioned_mailboxes
         WHERE user_id IS NOT NULL
           AND status IN ('active', 'archived')
        """
    )

    # 3. Backfill from OAuth tokens (personal accounts)
    op.execute(
        """
        INSERT INTO email.email_accounts
            (user_id, type, provider, address,
             is_active, is_default, oauth_token_id,
             sync_state, connected_at, created_at, updated_at)
        SELECT
            user_id,
            'personal',
            provider,
            provider_account_id,
            is_active,
            false,
            id,
            '{}'::jsonb,
            created_at,
            created_at,
            updated_at
          FROM email.oauth_tokens
        """
    )

    # 4. Mark first account per user as default
    op.execute(
        """
        WITH firsts AS (
            SELECT DISTINCT ON (user_id) id
              FROM email.email_accounts
             ORDER BY user_id, id ASC
        )
        UPDATE email.email_accounts ea
           SET is_default = true
          FROM firsts f
         WHERE ea.id = f.id
        """
    )

    # 5. Switch EmailMessage.account_id FK from oauth_tokens to email_accounts
    # 5a. Drop the old FK (anonymous in 001_initial → conventional name)
    op.execute(
        """
        DO $$
        DECLARE
            cname text;
        BEGIN
            SELECT con.conname INTO cname
              FROM pg_constraint con
              JOIN pg_class rel ON rel.oid = con.conrelid
              JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace
             WHERE nsp.nspname = 'email'
               AND rel.relname = 'email_messages'
               AND con.contype = 'f'
               AND con.conkey = ARRAY[
                   (SELECT attnum FROM pg_attribute
                     WHERE attrelid = rel.oid AND attname = 'account_id')
               ]::int2[];
            IF cname IS NOT NULL THEN
                EXECUTE 'ALTER TABLE email.email_messages DROP CONSTRAINT '
                        || quote_ident(cname);
            END IF;
        END $$;
        """
    )

    # 5b. Repoint values: account_id was oauth_tokens.id → map to email_accounts.id
    op.execute(
        """
        UPDATE email.email_messages m
           SET account_id = ea.id
          FROM email.email_accounts ea
         WHERE ea.oauth_token_id = m.account_id
           AND m.account_id IS NOT NULL
        """
    )

    # 5c. Add new FK
    op.create_foreign_key(
        "fk_email_messages_account_id",
        source_table="email_messages",
        referent_table="email_accounts",
        local_cols=["account_id"],
        remote_cols=["id"],
        ondelete="SET NULL",
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
    )

    # 6. provider_folder column on email_messages (canonical folder stays;
    # this preserves the original provider label like '[Gmail]/Sent Mail').
    op.add_column(
        "email_messages",
        sa.Column(
            "provider_folder",
            sa.String(length=255),
            nullable=False,
            server_default="",
        ),
        schema=SCHEMA,
    )

    # 7. Indexes for the unified inbox query and dedup-on-conflict UPSERT
    op.create_index(
        "ix_email_messages_user_account_folder_date",
        "email_messages",
        ["user_id", "account_id", "folder", sa.text("date DESC")],
        schema=SCHEMA,
    )
    op.execute(
        "CREATE UNIQUE INDEX ux_email_messages_account_message "
        "ON email.email_messages (account_id, message_id) "
        "WHERE message_id IS NOT NULL"
    )


def downgrade() -> None:
    # 1. Drop new indexes on email_messages
    op.execute("DROP INDEX IF EXISTS email.ux_email_messages_account_message")
    op.drop_index(
        "ix_email_messages_user_account_folder_date",
        table_name="email_messages",
        schema=SCHEMA,
    )

    # 2. Drop provider_folder
    op.drop_column("email_messages", "provider_folder", schema=SCHEMA)

    # 3. Drop new FK
    op.drop_constraint(
        "fk_email_messages_account_id",
        "email_messages",
        type_="foreignkey",
        schema=SCHEMA,
    )

    # 4. Repoint account_id back to oauth_tokens.id
    op.execute(
        """
        UPDATE email.email_messages m
           SET account_id = ea.oauth_token_id
          FROM email.email_accounts ea
         WHERE ea.id = m.account_id
           AND ea.oauth_token_id IS NOT NULL
        """
    )
    op.execute(
        """
        UPDATE email.email_messages
           SET account_id = NULL
         WHERE account_id IN (SELECT id FROM email.email_accounts WHERE oauth_token_id IS NULL)
        """
    )

    # 5. Restore old FK to oauth_tokens
    op.create_foreign_key(
        "email_messages_account_id_fkey",
        source_table="email_messages",
        referent_table="oauth_tokens",
        local_cols=["account_id"],
        remote_cols=["id"],
        ondelete="SET NULL",
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
    )

    # 6. Drop email_accounts
    op.execute("DROP INDEX IF EXISTS email.ux_email_accounts_default_per_user")
    op.drop_index(
        "ix_email_accounts_watch_expires_at",
        table_name="email_accounts",
        schema=SCHEMA,
    )
    op.drop_index(
        "ix_email_accounts_user_active",
        table_name="email_accounts",
        schema=SCHEMA,
    )
    op.drop_index(
        "ix_email_accounts_user_id",
        table_name="email_accounts",
        schema=SCHEMA,
    )
    op.drop_table("email_accounts", schema=SCHEMA)
