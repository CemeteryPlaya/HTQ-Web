"""Pydantic schemas package."""

from app.schemas.conference import ConferenceConfig, ConferenceYAMLSource, IceServer
from app.schemas.contact_request import (
    ContactRequestCreate,
    ContactRequestRead,
    ContactRequestReply,
    ContactRequestStats,
    ContactRequestUpdate,
)
from app.schemas.news import (
    NewsCreate,
    NewsRead,
    NewsTranslateRequest,
    NewsTranslateResponse,
    NewsUpdate,
)


__all__ = [
    "ConferenceConfig",
    "ConferenceYAMLSource",
    "IceServer",
    "ContactRequestCreate",
    "ContactRequestRead",
    "ContactRequestReply",
    "ContactRequestStats",
    "ContactRequestUpdate",
    "NewsCreate",
    "NewsRead",
    "NewsTranslateRequest",
    "NewsTranslateResponse",
    "NewsUpdate",
]
