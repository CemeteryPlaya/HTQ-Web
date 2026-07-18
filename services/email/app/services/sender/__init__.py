"""Per-provider outbound senders."""

from app.services.sender.base import SendResult, Sender
from app.services.sender.factory import get_sender

__all__ = ["Sender", "SendResult", "get_sender"]
