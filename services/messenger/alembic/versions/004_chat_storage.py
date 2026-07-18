"""Add per-room storage keys and structured attachment metadata.

Revision ID: 004_chat_storage
Revises: 003
"""

from __future__ import annotations

import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from app.core.settings import settings


revision = "004_chat_storage"
down_revision = "003"
branch_labels = None
depends_on = None

SCHEMA = settings.db_schema
TABLES = [
    "chat_user_replicas",
    "rooms",
    "room_participants",
    "messages",
    "chat_attachments",
    "user_keys",
]


def _ensure_tables_in_service_schema() -> None:
    for source_schema in ("auth", "public"):
        if source_schema == SCHEMA:
            continue
        for table in TABLES:
            op.execute(
                f"""
                DO $$
                BEGIN
                    IF EXISTS (
                        SELECT 1 FROM information_schema.tables
                        WHERE table_schema = '{source_schema}' AND table_name = '{table}'
                    ) AND NOT EXISTS (
                        SELECT 1 FROM information_schema.tables
                        WHERE table_schema = '{SCHEMA}' AND table_name = '{table}'
                    ) THEN
                        EXECUTE 'ALTER TABLE {source_schema}.{table} SET SCHEMA {SCHEMA}';
                    END IF;
                END $$;
                """
            )


def upgrade() -> None:
    op.execute(f'CREATE SCHEMA IF NOT EXISTS "{SCHEMA}"')
    _ensure_tables_in_service_schema()

    op.add_column(
        "rooms",
        sa.Column("storage_key", postgresql.UUID(as_uuid=True), nullable=True),
        schema=SCHEMA,
    )

    bind = op.get_bind()
    rows = bind.execute(sa.text(f'SELECT id FROM "{SCHEMA}"."rooms" WHERE storage_key IS NULL')).all()
    for row in rows:
        bind.execute(
            sa.text(
                f'UPDATE "{SCHEMA}"."rooms" '
                "SET storage_key = CAST(:storage_key AS uuid) WHERE id = :room_id"
            ),
            {"storage_key": str(uuid.uuid4()), "room_id": row.id},
        )

    op.alter_column(
        "rooms",
        "storage_key",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False,
        schema=SCHEMA,
    )
    op.create_unique_constraint("uq_rooms_storage_key", "rooms", ["storage_key"], schema=SCHEMA)

    op.add_column(
        "chat_attachments",
        sa.Column("room_id", sa.Integer(), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "chat_attachments",
        sa.Column("data_type", sa.String(length=40), server_default="other", nullable=False),
        schema=SCHEMA,
    )
    op.add_column(
        "chat_attachments",
        sa.Column("storage_path", sa.String(length=2048), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "chat_attachments",
        sa.Column("public_url", sa.String(length=2048), nullable=True),
        schema=SCHEMA,
    )
    op.create_index(
        op.f("ix_chat_attachments_room_id"),
        "chat_attachments",
        ["room_id"],
        unique=False,
        schema=SCHEMA,
    )
    op.create_foreign_key(
        "fk_chat_attachments_room_id_rooms",
        "chat_attachments",
        "rooms",
        ["room_id"],
        ["id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        ondelete="CASCADE",
    )

    op.execute(
        f"""
        UPDATE "{SCHEMA}"."chat_attachments" ca
        SET room_id = m.room_id
        FROM "{SCHEMA}"."messages" m
        WHERE ca.message_id = m.id AND ca.room_id IS NULL
        """
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_chat_attachments_room_id_rooms",
        "chat_attachments",
        type_="foreignkey",
        schema=SCHEMA,
    )
    op.drop_index(op.f("ix_chat_attachments_room_id"), table_name="chat_attachments", schema=SCHEMA)
    op.drop_column("chat_attachments", "public_url", schema=SCHEMA)
    op.drop_column("chat_attachments", "storage_path", schema=SCHEMA)
    op.drop_column("chat_attachments", "data_type", schema=SCHEMA)
    op.drop_column("chat_attachments", "room_id", schema=SCHEMA)

    op.drop_constraint("uq_rooms_storage_key", "rooms", type_="unique", schema=SCHEMA)
    op.drop_column("rooms", "storage_key", schema=SCHEMA)
