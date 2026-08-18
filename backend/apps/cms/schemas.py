"""Pydantic schemas for the ``cms`` app's HTTP layer.

Ported 1:1 from the FastAPI original (``services/cms/app/schemas/*.py``) —
field names are kept identical because the React frontend parses them as-is.
"""

from datetime import datetime
from typing import Generic, Optional, TypeVar, Union

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from apps.cms.models import NewsStatus


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
    renamed. Everything after ``ice_servers`` is an addition beyond the port,
    placed last so the ported fields keep their order:

    * ``enabled`` (Task 1.5) — whether the conference/SFU service is on in
      the service registry (``apps.core.services.service_enabled``);
    * ``wt_signaling_url`` / ``wt_certificate_hashes`` — WebTransport (QUIC)
      сигналинг: предпочтительный транспорт, WebSocket остаётся запасным.
      Пустой URL = QUIC-мост не развёрнут, фронт сразу идёт по WebSocket.
      Хэши нужны только для самоподписанного сертификата в dev
      (``new WebTransport(url, {serverCertificateHashes})``); с сертификатом
      от настоящего CA список пуст.
    """

    sfu_signaling_url: str = ""
    sfu_signaling_path: str = "/ws/sfu/"
    ice_servers: list[IceServer] = Field(default_factory=list)
    enabled: bool = True
    wt_signaling_url: str = ""
    wt_certificate_hashes: list[str] = Field(default_factory=list)


class ContactRequestListQuery(BaseModel):
    """Validates ``GET /contact-requests/`` query params.

    Mirrors the FastAPI original's ``Query(...)`` declarations
    (``services/cms/app/api/v1/contact_requests.py``) so out-of-range or
    malformed values 422 instead of being silently clamped/defaulted.
    """

    handled: Optional[bool] = None
    limit: int = Field(50, ge=1, le=500)
    offset: int = Field(0, ge=0)


# --- Taxonomy (categories, tags) --------------------------------------------
#
# Ported 1:1 from ``services/cms/app/schemas/news.py`` — field names/limits
# kept identical (frontend types: ``frontend/src/types/news.ts``).


class CategoryBase(BaseModel):
    slug: str = Field(..., max_length=120, pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str = Field(..., max_length=160, min_length=1)
    description: str = Field("", max_length=500)


class CategoryCreate(CategoryBase):
    pass


class CategoryUpdate(BaseModel):
    slug: Optional[str] = Field(None, max_length=120, pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: Optional[str] = Field(None, max_length=160, min_length=1)
    description: Optional[str] = Field(None, max_length=500)


class CategoryRead(CategoryBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime


class TagBase(BaseModel):
    slug: str = Field(..., max_length=80, pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str = Field(..., max_length=80, min_length=1)


class TagCreate(TagBase):
    pass


class TagUpdate(BaseModel):
    slug: Optional[str] = Field(None, max_length=80, pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: Optional[str] = Field(None, max_length=80, min_length=1)


class TagRead(TagBase):
    model_config = ConfigDict(from_attributes=True)
    id: int


# --- News --------------------------------------------------------------------
#
# Ported 1:1 from ``services/cms/app/schemas/news.py``. Unlike
# ``CategoryRead``/``TagRead`` (validated straight off the ORM instance),
# ``NewsRead`` is always built from a plain dict assembled by
# ``apps.cms.services.news_service.serialize_news`` — the Django ``News``
# model has both a legacy ``category`` string column AND a ``category_ref``
# FK, the same name clash the FastAPI original has between its ``category``
# string column and ``category_ref`` relationship. The FastAPI schema
# resolves it with ``validation_alias="category_ref"``; the Django port
# resolves it by having the service put the *category_ref* object under the
# dict key ``"category"`` directly, so no alias is needed here.


class NewsBase(BaseModel):
    title: str = Field(..., max_length=300, min_length=1)
    slug: str = Field(..., max_length=320, min_length=1)
    excerpt: str = Field("", max_length=500)
    content: str = ""
    image: Optional[str] = Field(None, max_length=500)
    category_id: Optional[int] = None
    author_id: Optional[int] = None
    status: NewsStatus = NewsStatus.DRAFT
    scheduled_at: Optional[datetime] = None


class NewsCreate(NewsBase):
    tag_ids: list[int] = Field(default_factory=list)


class NewsUpdate(BaseModel):
    title: Optional[str] = Field(None, max_length=300, min_length=1)
    slug: Optional[str] = Field(None, max_length=320, min_length=1)
    excerpt: Optional[str] = Field(None, max_length=500)
    content: Optional[str] = None
    image: Optional[str] = Field(None, max_length=500)
    category_id: Optional[int] = None
    author_id: Optional[int] = None
    status: Optional[NewsStatus] = None
    scheduled_at: Optional[datetime] = None
    tag_ids: Optional[list[int]] = None
    # Legacy compatibility — accepted but mapped onto `status`.
    published: Optional[bool] = None


class NewsRead(NewsBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    published: bool
    published_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    category: Optional[CategoryRead] = None
    tags: list[TagRead] = Field(default_factory=list)
    # Legacy denormalized field for transitional clients.
    summary: str = ""


class NewsTranslateRequest(BaseModel):
    """Порт ``services/cms/app/schemas/news.py::NewsTranslateRequest``."""

    target: str = Field("en", min_length=2, max_length=10)


class NewsTranslateResponse(BaseModel):
    """Порт ``::NewsTranslateResponse``. ``task_id`` у источника — id
    Dramatiq-сообщения; здесь это ``AsyncResult.id`` Celery-задачи
    (``apps.cms.tasks.translate_news``), тот же смысл — ручка для отслеживания
    поставленной в очередь работы."""

    task_id: str
    news_id: int
    target: str
    status: str = "queued"


T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    page: int
    page_size: int
    total: int
    has_next: bool


class NewsListQuery(BaseModel):
    """Validates ``GET /news/`` query params.

    Mirrors the FastAPI original's ``Query(...)`` declarations
    (``services/cms/app/api/v1/news.py::list_news``).
    """

    category: Optional[str] = Field(None, max_length=120)
    tag: Optional[str] = Field(None, max_length=80)
    status: Optional[NewsStatus] = None
    q: Optional[str] = Field(None, max_length=200)
    page: int = Field(1, ge=1)
    page_size: int = Field(12, ge=1, le=100)


# ── Приглашения в конференцию ──────────────────────────────────────────────

class ConferenceInviteCreate(BaseModel):
    room_id: str = Field(..., min_length=1, max_length=64)
    title: str = Field("", max_length=255)
    #: Пускать ли по ссылке людей без учётки. Выключается, когда зовут только
    #: коллег: тогда ссылка просто ведёт в комнату через обычный вход.
    allow_guests: bool = True
    ttl_hours: Optional[int] = Field(None, ge=1, le=24 * 90)
    #: 0 — без ограничения на число входов.
    max_uses: int = Field(0, ge=0, le=1000)


class ConferenceInviteRead(BaseModel):
    id: int
    room_id: str
    title: str
    #: Готовый адрес — им пользуются письма и сообщения. Браузеру он не
    #: указ: фронт собирает ссылку от собственного origin (см. ниже про
    #: token), потому что за прокси Host бэкенда может быть каким угодно.
    url: str
    token: str
    allow_guests: bool
    expires_at: datetime
    revoked: bool
    max_uses: int
    uses: int
    created_at: datetime


class ConferenceInvitePublic(BaseModel):
    """То, что видит человек по ссылке ДО входа.

    ``room_id`` заполняется ТОЛЬКО для сотрудника с действующим токеном: ему
    представляться незачем, он входит под собой. Анонимному посетителю
    комната не отдаётся — пока он не назвался, он не участник встречи.
    """

    title: str
    allow_guests: bool
    expires_at: datetime
    room_id: Optional[str] = None


class ConferenceGuestRequest(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=80)


class ConferenceGuestToken(BaseModel):
    access_token: str
    expires_in: int
    room_id: str
    display_name: str
    title: str
    #: Рантайм-конфиг конференции отдаётся вместе с токеном намеренно:
    #: /conference/config закрыт платформенным JWT, которого у гостя нет, а
    #: открывать его наружу ради адреса сигналинга — лишняя дырка.
    conference: ConferenceConfig


class ConferenceInviteSend(BaseModel):
    """Кому отправить ссылку. Каналы независимы: можно указать только один."""

    emails: list[EmailStr] = Field(default_factory=list, max_length=50)
    user_ids: list[int] = Field(default_factory=list, max_length=200)


class ConferenceInviteSendResult(BaseModel):
    emails_sent: int
    notified: int
    #: Отказ одного канала не отменяет другой — организатор должен видеть,
    #: что именно не дошло, а не гадать по молчанию.
    errors: list[str] = Field(default_factory=list)
