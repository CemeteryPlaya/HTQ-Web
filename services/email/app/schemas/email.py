"""Email Pydantic Schemas."""

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class OAuthTokenRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    provider: str
    provider_account_id: str
    expires_at: datetime
    is_active: bool


class EmailAttachmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    filename: str
    mime_type: str
    size: int


class EmailMessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    account_id: Optional[int] = None
    subject: str
    snippet: str
    sender_email: str
    sender_name: Optional[str]
    to_recipients: list[dict]
    cc_recipients: list[dict]
    date: datetime
    is_read: bool
    is_flagged: bool
    has_attachments: bool
    folder: str
    provider_folder: Optional[str] = ""


class EmailMessageDetail(EmailMessageRead):
    body_html: Optional[str] = None
    body_text: Optional[str] = None
    attachments: list[EmailAttachmentRead] = []


class EmailSendRequest(BaseModel):
    account_id: int
    to_recipients: list[dict] # [{"email": "a@b.com", "name": "A"}]
    cc_recipients: list[dict] = []
    bcc_recipients: list[dict] = []
    subject: str
    body_html: Optional[str] = None
    body_text: Optional[str] = None
    attachment_ids: list[uuid.UUID] = [] # file_metadata_id
