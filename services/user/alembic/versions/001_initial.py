"""Initial schema — users table

Replaces Django's auth.User + mainView.Profile with a single table.
Migration ID: 001
"""

from alembic import op
import sqlalchemy as sa

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("username", sa.String(150), unique=True, nullable=False),
        sa.Column("email", sa.String(254), unique=True, nullable=False),
        sa.Column("password_hash", sa.String(256), nullable=False),
        sa.Column("first_name", sa.String(150), nullable=False, server_default=""),
        sa.Column("last_name", sa.String(150), nullable=False, server_default=""),
        sa.Column("patronymic", sa.String(100), nullable=False, server_default=""),
        sa.Column("display_name", sa.String(100), nullable=False, server_default=""),
        sa.Column("bio", sa.Text, nullable=False, server_default=""),
        sa.Column("phone", sa.String(30), nullable=False, server_default=""),
        sa.Column("avatar_url", sa.String(500), nullable=True),
        sa.Column("settings", sa.JSON, nullable=False, server_default="{}"),
        sa.Column(
            "status",
            sa.Enum("pending", "active", "suspended", "rejected", name="userstatus"),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("is_staff", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("is_superuser", sa.Boolean, nullable=False, server_default="false"),
        sa.Column(
            "must_change_password", sa.Boolean, nullable=False, server_default="false"
        ),
        sa.Column("date_joined", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_login", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    # Indexes
    op.create_index("ix_users_email", "users", ["email"])
    op.create_index("ix_users_username", "users", ["username"])
    op.create_index("ix_users_status", "users", ["status"])


def downgrade() -> None:
    op.drop_index("ix_users_status", table_name="users")
    op.drop_index("ix_users_username", table_name="users")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
    op.execute("DROP TYPE IF EXISTS userstatus")
