"""Driver lookup by provider name. Imports lazily to keep cold starts cheap."""

from __future__ import annotations

from app.services.sync.base import SyncDriver


def get_driver(provider: str) -> SyncDriver:
    if provider == "google":
        from app.services.sync.gmail import GmailSyncDriver
        return GmailSyncDriver()
    if provider == "microsoft":
        from app.services.sync.microsoft import MicrosoftSyncDriver
        return MicrosoftSyncDriver()
    if provider == "mailcow":
        from app.services.sync.mailcow_imap import MailcowImapSyncDriver
        return MailcowImapSyncDriver()
    raise ValueError(f"Unsupported sync provider: {provider!r}")
