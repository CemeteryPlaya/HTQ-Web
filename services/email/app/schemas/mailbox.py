"""Pydantic schemas for mailbox provisioning admin API."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


MailboxStatus = Literal["active", "archived", "deleted", "error"]


class MailboxCreateRequest(BaseModel):
    """Body for `POST /api/email/v1/mailboxes/`."""
    # When `local_part` is empty, the server auto-generates from first/last name
    # (transliterated, e.g. "Иван Иванов" → "i.ivanov"). With a conflict it
    # appends 2, 3, … until unique.
    local_part: str = Field(default="", max_length=64, description="Part before @; '' = autogen from name")
    first_name: str = Field(default="", max_length=150)
    last_name: str = Field(default="", max_length=150)
    full_name: str = Field(default="", max_length=255, description="Display name in mailbox metadata")
    # When `password` is empty, the server generates a strong random one and
    # returns it once in the response (admin must capture it).
    password: str = Field(default="", description="Plain text; '' = autogen and return once")
    quota_mb: int = Field(default=0, ge=0, description="0 = use MAILCOW_DEFAULT_QUOTA_MB")
    user_id: int | None = Field(default=None, description="Link to platform user; one mailbox per user_id")
    must_change_password: bool = Field(default=True)


class MailboxUpdateRequest(BaseModel):
    """Body for `PATCH /api/email/v1/mailboxes/{id}/`."""
    full_name: str | None = Field(default=None, max_length=255)
    quota_mb: int | None = Field(default=None, ge=0)


class MailboxResetPasswordRequest(BaseModel):
    new_password: str = Field(default="", description="'' = autogen and return once")
    force_change: bool = Field(default=True)


class MailboxOut(BaseModel):
    id: int
    user_id: int | None
    local_part: str
    domain: str
    address: str
    status: MailboxStatus
    quota_mb: int
    display_name: str | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None
    deleted_at: datetime | None

    model_config = {"from_attributes": True}


class MailboxCreatedResponse(MailboxOut):
    """Returned by POST /mailboxes/ — includes the generated password ONCE.

    `generated_password` is None if the admin supplied their own password.
    """
    generated_password: str | None = None


_EMAIL_RE = r"^[^\s@]+@[^\s@]+\.[^\s@]+$"


class AliasCreateRequest(BaseModel):
    address: str = Field(..., max_length=255)
    goto: str = Field(..., description="Comma-separated list of destination addresses")
    active: bool = True

    @field_validator("address")
    @classmethod
    def _validate_address(cls, v: str) -> str:
        import re
        if not re.match(_EMAIL_RE, v):
            raise ValueError("invalid email address")
        return v


class AliasOut(BaseModel):
    id: int
    address: str
    goto: str
    active: bool


class ForwardingSetRequest(BaseModel):
    forward_to: str = Field(..., max_length=255)
    keep_local_copy: bool = True

    @field_validator("forward_to")
    @classmethod
    def _validate_forward_to(cls, v: str) -> str:
        import re
        if not re.match(_EMAIL_RE, v):
            raise ValueError("invalid email address")
        return v
