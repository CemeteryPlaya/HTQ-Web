"""Public surface of the shared object-storage package.

Re-exports the pieces future app teams need (``get_storage`` plus the
storage classes/protocol from ``htqweb.storage.s3``, and the signed-URL
helpers from ``htqweb.storage.signed_url``) so callers can do
``from htqweb.storage import get_storage, signed_query`` instead of
reaching into the submodules directly. The deep modules remain importable
as-is (``htqweb.storage.s3``, ``htqweb.storage.signed_url``) — this is
purely additive.
"""

from __future__ import annotations

from htqweb.storage.s3 import LocalStorage, S3Storage, Storage, get_storage
from htqweb.storage.signed_url import sign, signed_query, verify

__all__ = [
    "get_storage",
    "Storage",
    "LocalStorage",
    "S3Storage",
    "sign",
    "verify",
    "signed_query",
]
