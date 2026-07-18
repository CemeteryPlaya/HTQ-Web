"""Reference data sources — Lark-Base-style lookup tables that `reference`
form widgets read their options from (and filter by a parent field for
dependent selects)."""

from sqlalchemy import JSON, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, BaseModel

JSON_VARIANT = JSON().with_variant(JSONB(), "postgresql")


class RequestReferenceSource(BaseModel):
    __tablename__ = "request_reference_sources"

    slug: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    columns_json: Mapped[list] = mapped_column(JSON_VARIANT, nullable=False, default=list, server_default="[]")
    created_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # When set, this source is the auto-maintained data table of a template
    # (Lark "Управление данными" / Base). NULL = a manually-managed source.
    template_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    # Extra viewers of a template data table, granted by its owner (on top of
    # the template creator + process admins).
    access_ids: Mapped[list] = mapped_column(JSON_VARIANT, nullable=False, default=list, server_default="[]")

    rows: Mapped[list["RequestReferenceRow"]] = relationship(
        "RequestReferenceRow", back_populates="source", cascade="all, delete-orphan",
    )

    @property
    def columns(self) -> list:
        return self.columns_json or []


class RequestReferenceRow(Base):
    __tablename__ = "request_reference_rows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("request_reference_sources.id", ondelete="CASCADE"), nullable=False, index=True
    )
    data_json: Mapped[dict] = mapped_column(JSON_VARIANT, nullable=False, default=dict, server_default="{}")
    # For rows in a template's data table: the request instance this row mirrors
    # (used to upsert the row on every instance change). NULL for manual rows.
    instance_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

    source: Mapped["RequestReferenceSource"] = relationship("RequestReferenceSource", back_populates="rows")

    @property
    def data(self) -> dict:
        return self.data_json or {}
