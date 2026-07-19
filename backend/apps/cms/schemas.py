"""Pydantic schemas for the ``cms`` app's HTTP layer.

Ported 1:1 from the FastAPI original (``services/cms/app/schemas/*.py``) —
field names are kept identical because the React frontend parses them as-is.
"""

from datetime import datetime
from typing import Optional, Union

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


class IceServer(BaseModel):
    """Ported 1:1 from ``services/cms/app/schemas/conference.py``."""

    urls: Union[str, list[str]]
    username: Optional[str] = None
    credential: Optional[str] = None


class ConferenceConfig(BaseModel):
    """Response shape for ``GET /api/cms/v1/conference/config``.

    Field-for-field port of the FastAPI original's ``ConferenceConfig``
    (``services/cms/app/schemas/conference.py``) — the frontend's WebRTC
    layer (``ConferencePage.tsx``) parses these names as-is, so they are not
    renamed. ``enabled`` is the one addition beyond the port (Task 1.5):
    whether the conference/SFU service itself is on in the service registry
    (``apps.core.services.service_enabled``), placed last so it doesn't
    disturb the ported fields.
    """

    sfu_signaling_url: str = ""
    sfu_signaling_path: str = "/ws/sfu/"
    ice_servers: list[IceServer] = Field(default_factory=list)
    enabled: bool = True


class ContactRequestListQuery(BaseModel):
    """Validates ``GET /contact-requests/`` query params.

    Mirrors the FastAPI original's ``Query(...)`` declarations
    (``services/cms/app/api/v1/contact_requests.py``) so out-of-range or
    malformed values 422 instead of being silently clamped/defaulted.
    """

    handled: Optional[bool] = None
    limit: int = Field(50, ge=1, le=500)
    offset: int = Field(0, ge=0)
