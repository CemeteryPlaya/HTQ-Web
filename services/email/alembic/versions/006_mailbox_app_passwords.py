"""Add encrypted SMTP/IMAP app-password column to provisioned_mailboxes.

Mailcow doesn't expose mailbox plaintext passwords, so for SMTP submission
(Phase 7) and IMAP IDLE (Phase 6 supervisor) we generate a per-mailbox
"app password" via Mailcow's ``/add/app-passwd/mailbox`` endpoint, encrypt
it via the same AES-256-GCM key used for OAuth tokens, and store it here.

Revision ID: 006_mailbox_app_passwords
Revises: 005_email_accounts
"""

import sqlalchemy as sa
from alembic import op


revision = "006_mailbox_app_passwords"
down_revision = "005_email_accounts"
branch_labels = None
depends_on = None


SCHEMA = "email"


def upgrade() -> None:
    op.add_column(
        "provisioned_mailboxes",
        sa.Column("encrypted_smtp_app_password", sa.Text(), nullable=True),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_column(
        "provisioned_mailboxes",
        "encrypted_smtp_app_password",
        schema=SCHEMA,
    )
