"""Pydantic schemas for ContactRequest."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class ContactRequestCreate(BaseModel):
    first_name: str = Field("", max_length=150)
    last_name: str = Field("", max_length=150)
    email: EmailStr
    message: str = ""


class ContactRequestReply(BaseModel):
    reply_message: str = Field(..., min_length=1)


class ContactRequestUpdate(BaseModel):
    handled: Optional[bool] = None
    reply_message: Optional[str] = None


class ContactRequestRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    first_name: str
    last_name: str
    email: str
    message: str
    handled: bool
    replied_at: Optional[datetime]
    replied_by_id: Optional[int]
    reply_message: str
    created_at: datetime


class ContactRequestStats(BaseModel):
    unhandled: int
