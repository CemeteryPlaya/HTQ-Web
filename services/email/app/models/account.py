"""Unified per-user email account.

One row per mailbox the user has linked to the platform — either a Mailcow
``ProvisionedMailbox`` (corporate) or an ``OAuthToken`` for an external
provider (personal Gmail / Outlook). The frontend lists all of these in a
single account-selector and routes folder/list/send queries through
``account_id``.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class EmailAccount(Base):
    __tablename__ = "email_accounts"
    __table_args__ = (
        UniqueConstraint("user_id", "address", name="uq_email_accounts_user_address"),
        UniqueConstraint("mailbox_id", name="uq_email_accounts_mailbox_id"),
        UniqueConstraint("oauth_token_id", name="uq_email_accounts_oauth_token_id"),
        CheckConstraint(
            "type IN ('corporate','personal')",
            name="ck_email_accounts_type",
        ),
        CheckConstraint(
            "provider IN ('mailcow','google','microsoft')",
            name="ck_email_accounts_provider",
        ),
        CheckConstraint(
            "(type = 'corporate' AND mailbox_id IS NOT NULL AND oauth_token_id IS NULL) "
            "OR (type = 'personal' AND oauth_token_id IS NOT NULL AND mailbox_id IS NULL)",
            name="ck_email_accounts_type_consistency",
        ),
        {"schema": "email"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # FK by id only — user-service owns the canonical user row.
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)

    # 'corporate' (Mailcow) | 'personal' (Gmail/Outlook)
    type: Mapped[str] = mapped_column(String(16), nullable=False)
    # 'mailcow' | 'google' | 'microsoft'
    provider: Mapped[str] = mapped_column(String(16), nullable=False)

    address: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Compose default — exactly one per user (partial unique idx in migration).
    is_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    # False = sync paused (user deactivated, account disconnected, etc.)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )

    # Exactly one of these is set, enforced by ck_email_accounts_type_consistency.
    mailbox_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("email.provisioned_mailboxes.id", ondelete="SET NULL"),
        nullable=True,
    )
    oauth_token_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("email.oauth_tokens.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Per-provider opaque cursor:
    #   google:    {"history_id": "...", "watch_topic": "...", "label_ids": [...]}
    #   microsoft: {"delta_link": "...", "subscription_id": "..."}
    #   mailcow:   {"uidvalidity": ..., "uidnext": {"INBOX": ..., "Sent": ...}}
    sync_state: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    last_sync_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_sync_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Push subscription expiration — scheduler renews before this time.
    watch_expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    connected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    mailbox = relationship("ProvisionedMailbox", lazy="joined")
    oauth_token = relationship("OAuthToken", lazy="joined")
