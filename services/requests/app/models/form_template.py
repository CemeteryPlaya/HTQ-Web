"""Form templates + immutable versions (schema_json + workflow_json)."""

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, BaseModel

# JSONB on Postgres, generic JSON on SQLite (unit tests).
JSON_VARIANT = JSON().with_variant(JSONB(), "postgresql")


class RequestFormTemplate(BaseModel):
    __tablename__ = "request_form_templates"

    project_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("request_projects.id", ondelete="SET NULL"), index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    icon: Mapped[str] = mapped_column(String(50), nullable=False, default="", server_default="")
    color: Mapped[str] = mapped_column(String(20), nullable=False, default="#3b82f6", server_default="#3b82f6")
    # Basic Info config (Lark builder step 1): group, who_can_submit,
    # submit_user_ids, show_on_workplace, prohibit_admin_manage, process_admin_ids.
    config_json: Mapped[dict] = mapped_column(JSON_VARIANT, nullable=False, default=dict, server_default="{}")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    # Lifecycle: 'active' (usable), 'inactive' (deactivated — admins still see it
    # in Шаблоны, submitting is blocked), 'deleted' (soft-deleted — hidden, form
    # blocked, but its data table / reference data is preserved).
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active", server_default="active")
    created_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Denormalized pointer to the latest published version (no FK — would be
    # circular with versions; SQLite cannot ALTER ADD CONSTRAINT).
    current_version_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    versions: Mapped[list["RequestFormTemplateVersion"]] = relationship(
        "RequestFormTemplateVersion", back_populates="template",
        cascade="all, delete-orphan", order_by="RequestFormTemplateVersion.version",
    )

    __table_args__ = (UniqueConstraint("project_id", "slug", name="uq_request_form_templates_project_slug"),)


class RequestFormTemplateVersion(Base):
    __tablename__ = "request_form_template_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    template_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("request_form_templates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_json: Mapped[dict] = mapped_column(JSON_VARIANT, nullable=False)
    workflow_json: Mapped[dict] = mapped_column(JSON_VARIANT, nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    published_by: Mapped[int | None] = mapped_column(Integer, nullable=True)

    template: Mapped["RequestFormTemplate"] = relationship("RequestFormTemplate", back_populates="versions")

    __table_args__ = (UniqueConstraint("template_id", "version", name="uq_request_form_template_versions_tv"),)
