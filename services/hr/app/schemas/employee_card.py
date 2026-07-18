"""Т-2 card section schemas. Monetary fields serialize as strings."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel


class CardFinancial(BaseModel):
    salary: str | None = None
    bonus: str | None = None
    bank_account: str | None = None


class CardPersonal(BaseModel):
    passport_data: str | None = None
    inn: str | None = None
    birth_date: date | None = None
    birth_place: str | None = None
    citizenship: str | None = None


class CardCerts(BaseModel):
    sro_permit_number: str | None = None
    sro_permit_expiry: date | None = None
    safety_cert_number: str | None = None
    safety_cert_expiry: date | None = None


class EmployeeCardT2Patch(BaseModel):
    financial: CardFinancial | None = None
    personal: CardPersonal | None = None
    certs: CardCerts | None = None
