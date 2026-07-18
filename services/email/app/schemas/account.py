"""Pydantic schemas for the unified email_accounts API."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class EmailAccountRead(BaseModel):
    """One row in the user's account selector."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    type: str  # 'corporate' | 'personal'
    provider: str  # 'mailcow' | 'google' | 'microsoft'
    address: str
    display_name: Optional[str] = None
    is_default: bool
    is_active: bool
    last_sync_at: Optional[datetime] = None
    last_sync_error: Optional[str] = None
    watch_expires_at: Optional[datetime] = None
    connected_at: datetime
    unread_count: int = 0


class EmailAccountSyncResponse(BaseModel):
    """Returned by POST /accounts/{id}/sync/."""

    account_id: int
    queued_at: datetime
    status: str = "queued"
