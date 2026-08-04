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


# ── Блоки главной страницы ───────────────────────────────────────────────────
#
# Две формы одних и тех же данных:
#   * публичная (``HomeSectionPublic``) — уже локализованная, по одному
#     значению на поле: лендингу незачем знать про существование второго языка;
#   * редакторская (``HomeSectionAdmin``) — оба языка сразу, чтобы форма
#     показывала вкладки RU/EN без второго запроса.

class HomeItemPublic(BaseModel):
    id: int
    title: str = ""
    description: str = ""
    value: str = ""
    icon: str = ""
    image: str = ""
    link: str = ""


class HomeSectionPublic(BaseModel):
    id: int
    key: str
    layout: str = "features_grid"
    is_system: bool = False
    tag: str = ""
    title: str = ""
    description: str = ""
    items: list[HomeItemPublic] = []


class HomeItemAdmin(BaseModel):
    id: int
    title_ru: str = ""
    title_en: str = ""
    description_ru: str = ""
    description_en: str = ""
    value: str = ""
    icon: str = ""
    image: str = ""
    link: str = ""
    is_visible: bool = True
    order: int = 0


class HomeSectionAdmin(BaseModel):
    id: int
    key: str
    layout: str = "features_grid"
    is_system: bool = False
    tag_ru: str = ""
    tag_en: str = ""
    title_ru: str = ""
    title_en: str = ""
    description_ru: str = ""
    description_en: str = ""
    is_visible: bool = True
    order: int = 0
    items: list[HomeItemAdmin] = []


class HomeSectionUpdate(BaseModel):
    """PATCH секции. Все поля необязательны — форма шлёт только изменённое.

    ``key`` менять нельзя: по нему React-компонент находит свои данные, и
    переименование молча оставило бы секцию без макета. В схеме его нет вовсе,
    так что попытка прислать key просто игнорируется.
    """
    tag_ru: str | None = None
    tag_en: str | None = None
    title_ru: str | None = None
    title_en: str | None = None
    description_ru: str | None = None
    description_en: str | None = None
    is_visible: bool | None = None


class HomeItemUpsert(BaseModel):
    title_ru: str = ""
    title_en: str = ""
    description_ru: str = ""
    description_en: str = ""
    value: str = ""
    icon: str = ""
    image: str = ""
    link: str = ""
    is_visible: bool = True


class HomeItemUpdate(BaseModel):
    title_ru: str | None = None
    title_en: str | None = None
    description_ru: str | None = None
    description_en: str | None = None
    value: str | None = None
    icon: str | None = None
    image: str | None = None
    link: str | None = None
    is_visible: bool | None = None


class HomeReorder(BaseModel):
    """Массовая перестановка: список id в нужном порядке.

    Одним запросом, а не PATCH на каждую строку: перетаскивание меняет позиции
    сразу нескольким соседям, и построчная запись оставила бы порядок битым,
    если часть запросов не дойдёт.
    """
    ids: list[int]


class HomeSectionCreate(BaseModel):
    """Создание блока из интерфейса.

    ``key`` не спрашиваем: он служебный (по нему рендерер находит макет) и
    редактору не нужен — сервер выведет его из заголовка и разведёт коллизии
    сам. Ручной ввод дал бы поле, в котором нечего написать правильно.
    """
    title_ru: str
    title_en: str = ""
    layout: str = "features_grid"
    tag_ru: str = ""
    tag_en: str = ""
    description_ru: str = ""
    description_en: str = ""
