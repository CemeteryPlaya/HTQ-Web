"""Provisioned mailboxes (Mailcow-backed).

One row per mailbox we created. Tracks our local state (status, owner) and
mirrors the minimum needed to render the admin UI without round-tripping
to Mailcow on every list. Heavier metadata (last login, message count) is
fetched live from Mailcow on demand.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ProvisionedMailbox(Base):
    __tablename__ = "provisioned_mailboxes"
    __table_args__ = (
        UniqueConstraint("address", name="uq_provisioned_mailboxes_address"),
        UniqueConstraint("user_id", name="uq_provisioned_mailboxes_user_id"),
        {"schema": "email"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # FK by ID only — user-service owns the canonical user row, no DB-level FK
    # because the table lives in a different schema/owner-service.
    user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)

    # Address parts kept separate so we can rename/move-domain without parsing.
    local_part: Mapped[str] = mapped_column(String(255), nullable=False)
    domain: Mapped[str] = mapped_column(String(255), nullable=False)
    address: Mapped[str] = mapped_column(String(255), nullable=False, index=True)

    # 'active'   — Mailcow active=1, mailbox receives mail
    # 'archived' — Mailcow active=0, no inbound, data preserved (stage 1 of delete)
    # 'deleted'  — Mailcow record removed, our row kept as audit trail (stage 2)
    # 'error'    — last provisioning attempt failed (see last_error)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active", index=True)

    quota_mb: Mapped[int] = mapped_column(Integer, nullable=False, default=1024)
    display_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # AES-256-GCM-encrypted Mailcow app-password used for SMTP submission
    # (phase 7) and IMAP IDLE (phase 6 supervisor). Generated at
    # provision time via Mailcow's `/add/app-passwd/mailbox`.
    encrypted_smtp_app_password: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )
    archived_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
