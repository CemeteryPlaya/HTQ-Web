"""Pydantic schemas for Messenger Service."""

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, computed_field


class UserReplicaRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    first_name: str
    last_name: str
    avatar_url: Optional[str]
    is_active: bool
    # System bots (Календарь / Задачи / Почта / Файлы / Новости) carry
    # ``is_bot=True`` so the frontend can render a BOT badge and pin them
    # to the top of the chat list.
    is_bot: bool = False

    @computed_field  # type: ignore[misc]
    @property
    def full_name(self) -> str:
        """Display label used by the chat picker so the client doesn't have
        to compose it. Falls back to ``username`` for users with empty
        first/last name (e.g., legacy seed data)."""
        return f"{self.first_name} {self.last_name}".strip() or self.username

    @computed_field  # type: ignore[misc]
    @property
    def user_id(self) -> int:
        """Echo of ``id`` under the name the frontend ``ChatUser`` type
        uses for filtering ("don't show me in the user picker"). Without
        this alias both sides compare ``undefined !== undefined`` and the
        whole list collapses to empty."""
        return self.id


class RoomParticipantRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    user_id: int
    role: str
    last_read_message_id: Optional[uuid.UUID]
    user: Optional[UserReplicaRead]
    # Populated server-side only for the *requesting* user's participant row
    # in the /rooms list endpoint. Other participants' counts stay 0 — they're
    # not the caller's business and computing them would explode the query.
    unread_count: int = 0


import re as _re

_ATT_ID_RE = _re.compile(r"/attachments/file/([0-9a-fA-F-]{36})")


def _refresh_signed_avatar(url: Optional[str]) -> Optional[str]:
    """Re-sign a stored attachment URL on the fly.

    Group avatars are uploaded via ``POST /attachments/upload/`` and the
    response carries a *signed* URL with an ``exp`` (Unix timestamp) baked
    in. Storing that URL verbatim in ``rooms.avatar_url`` works until the
    signature expires — after which every ``<img src>`` returns 403.

    To keep the column simple (it stays a plain ``VARCHAR``), we re-sign
    on every serialization: extract the attachment UUID from the path and
    mint a fresh ``signed_query`` with a TTL that resets each time the UI
    fetches the room. External URLs (e.g. media-service avatars or absolute
    https URLs) pass through unchanged.
    """
    if not url:
        return url
    m = _ATT_ID_RE.search(url)
    if not m:
        return url
    from app.services.signed_url import signed_query

    attachment_id = m.group(1)
    return f"/api/messenger/v1/attachments/file/{attachment_id}?{signed_query(attachment_id)}"


class RoomRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: int
    storage_key: uuid.UUID
    name: Optional[str]
    room_type: str
    is_e2ee: bool
    created_at: datetime
    updated_at: Optional[datetime] = None
    # Mirror the raw column under an underscore-prefixed alias and expose a
    # re-signed version through ``avatar_url`` (see ``_refresh_signed_avatar``).
    avatar_url_raw: Optional[str] = Field(default=None, alias="avatar_url", exclude=True)
    participants: list[RoomParticipantRead] = []
    # Latest message, attached by the room-list endpoint via a separate
    # query (loading the relationship eagerly would pull every message in
    # the room, which is wasteful — see ``rooms.list_user_rooms``).
    last_message: Optional["MessageRead"] = None

    @computed_field  # type: ignore[misc]
    @property
    def avatar_url(self) -> Optional[str]:
        return _refresh_signed_avatar(self.avatar_url_raw)


class RoomCreate(BaseModel):
    name: Optional[str] = None
    room_type: str = "direct"
    is_e2ee: bool = False
    avatar_url: Optional[str] = None
    # Required: ids of every user that should be a member, NOT including the
    # caller (the service adds them automatically as admin). For direct chats
    # the list must have exactly one entry.
    participant_ids: list[int]


class RoomUpdate(BaseModel):
    """Patch a room's display fields. Only ``group`` rooms accept these.

    Either field may be omitted — ``None`` means «не трогать». An empty string
    is the explicit way to clear the value (e.g. ``avatar_url=""`` removes
    the photo and the UI falls back to the placeholder).
    """

    name: Optional[str] = None
    avatar_url: Optional[str] = None


class ChatAttachmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    room_id: Optional[int]
    message_id: Optional[uuid.UUID]
    file_metadata_id: Optional[uuid.UUID]
    filename: str
    size: int
    content_type: str
    data_type: str
    storage_path: Optional[str] = None
    thumbnail_path: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    created_at: datetime

    @computed_field  # type: ignore[misc]
    @property
    def url(self) -> Optional[str]:
        """Fresh per-serialization signed redirect URL.

        The HMAC signature lives only for ``attachment_signed_url_ttl``
        seconds, so we mint a new one on every read instead of trusting the
        stale ``public_url`` snapshot saved at upload time. Browsers can
        embed the result in ``<img src>`` directly — the redirect endpoint
        forwards to a presigned S3 URL.
        """
        if not self.storage_path:
            return None
        from app.services.signed_url import signed_query

        return f"/api/messenger/v1/attachments/file/{self.id}?{signed_query(str(self.id))}"

    @computed_field  # type: ignore[misc]
    @property
    def thumbnail_url(self) -> Optional[str]:
        """Signed redirect URL for the generated thumbnail.

        ``NULL`` when the attachment is not an image (no thumb was generated)
        or for legacy rows uploaded before migration 006. UI must fall back
        to ``url`` in that case so behaviour stays sane during rollout.
        """
        if not self.thumbnail_path:
            return None
        from app.services.signed_url import signed_query

        return f"/api/messenger/v1/attachments/file/{self.id}/thumb?{signed_query(str(self.id))}"


class MessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    room_id: int
    sender_id: Optional[int]
    content: str
    is_encrypted: bool
    is_edited: bool
    created_at: datetime
    sender: Optional[UserReplicaRead] = None
    attachments: list[ChatAttachmentRead] = []


# Resolve the forward-ref ``"MessageRead"`` referenced by ``RoomRead``.
# Pydantic v2 needs an explicit rebuild after the dependent class is defined.
RoomRead.model_rebuild()


class MessageCreate(BaseModel):
    room_id: int
    content: str
    is_encrypted: bool = False
    metadata_json: Optional[dict] = None
    attachment_ids: list[uuid.UUID] = [] # list of file_metadata_id from media-service


class UserKeyBase(BaseModel):
    public_identity_key: str
    signed_pre_key: str
    signature: str


class UserKeyCreate(UserKeyBase):
    device_id: str


class UserKeyRead(UserKeyBase):
    model_config = ConfigDict(from_attributes=True)
    user_id: int
    device_id: str
