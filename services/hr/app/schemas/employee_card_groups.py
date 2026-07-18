"""Т-2 repeating-group schemas (stored in Mongo)."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel


class EducationItem(BaseModel):
    institution: str = ""
    degree: str = ""
    field: str = ""
    year_from: int | None = None
    year_to: int | None = None


class ExperienceItem(BaseModel):
    org: str = ""
    position: str = ""
    date_from: date | None = None
    date_to: date | None = None
    note: str = ""


class RelativeItem(BaseModel):
    relation: str = ""
    full_name: str = ""
    birth_date: date | None = None
    note: str = ""


class EmployeeGroups(BaseModel):
    education: list[EducationItem] = []
    experience: list[ExperienceItem] = []
    relatives: list[RelativeItem] = []
