"""Department file metadata stored by HR service."""

from __future__ import annotations

from sqlalchemy import BigInteger, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel


class DepartmentFileFolder(BaseModel):
    __tablename__ = "hr_department_file_folders"
    __table_args__ = (
        UniqueConstraint("department_id", "name", name="uq_hr_department_file_folders_department_name"),
    )

    department_id: Mapped[int] = mapped_column(
        ForeignKey("hr_departments.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    created_by_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    department: Mapped["Department"] = relationship("Department")  # noqa: F821
    files: Mapped[list["DepartmentFile"]] = relationship(
        "DepartmentFile",
        back_populates="file_folder",
        passive_deletes=True,
    )


class DepartmentFile(BaseModel):
    __tablename__ = "hr_department_files"

    department_id: Mapped[int] = mapped_column(
        ForeignKey("hr_departments.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    file_folder_id: Mapped[int | None] = mapped_column(
        ForeignKey("hr_department_file_folders.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    media_file_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    file_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    mime_type: Mapped[str] = mapped_column(String(255), nullable=False, default="application/octet-stream")
    uploaded_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    uploaded_by_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")

    department: Mapped["Department"] = relationship("Department")  # noqa: F821
    file_folder: Mapped[DepartmentFileFolder | None] = relationship(
        "DepartmentFileFolder",
        back_populates="files",
    )
