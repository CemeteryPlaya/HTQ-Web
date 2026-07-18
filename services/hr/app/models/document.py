"""Document model."""

from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel


class Document(BaseModel):
    __tablename__ = "hr_documents"

    employee_id: Mapped[int] = mapped_column(ForeignKey("hr_employees.id"))
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    doc_type: Mapped[str] = mapped_column(String(50), nullable=False)  # contract | order | certificate
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False, default="application/octet-stream")
    uploaded_by: Mapped[int] = mapped_column(ForeignKey("hr_employees.id"))
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSON)

    employee: Mapped[Employee] = relationship(  # noqa: F821
        "Employee",
        back_populates="documents",
        foreign_keys=[employee_id],
    )

    def __repr__(self) -> str:
        return f"<Document(id={self.id}, title='{self.title}', employee_id={self.employee_id})>"
