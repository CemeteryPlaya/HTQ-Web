"""Провижининг корпоративных ящиков на почтовом сервере.

Точка входа — ``factory.get_provisioner()``; контракт — ``base.py``.
"""
from apps.mail.services.provisioning.base import (
    MailboxProvisioner,
    ProvisioningError,
    RemoteListingUnsupported,
    RemoteMailbox,
)
from apps.mail.services.provisioning.factory import (
    describe,
    get_provisioner,
    resolve_provisioner_name,
)

__all__ = [
    "MailboxProvisioner",
    "ProvisioningError",
    "RemoteListingUnsupported",
    "RemoteMailbox",
    "describe",
    "get_provisioner",
    "resolve_provisioner_name",
]
