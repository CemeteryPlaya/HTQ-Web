"""Pydantic schemas for conference runtime config."""

from typing import Optional, Union

from pydantic import BaseModel, Field


class IceServer(BaseModel):
    urls: Union[str, list[str]]
    username: Optional[str] = None
    credential: Optional[str] = None


class ConferenceConfig(BaseModel):
    """Response shape for GET /api/cms/v1/conference/config.

    Mirrors Django ``ConferenceConfigView`` response: signaling URL, path,
    and (optional) TURN/STUN ICE servers.
    """

    sfu_signaling_url: str = ""
    sfu_signaling_path: str = "/ws/sfu/"
    ice_servers: list[IceServer] = Field(default_factory=list)


class ConferenceYAMLSource(BaseModel):
    """Structure of ``app/data/conference.yaml`` on disk."""

    sfu_url: str = ""
    sfu_path: str = "/ws/sfu/"
    ice_servers: list[IceServer] = Field(default_factory=list)
