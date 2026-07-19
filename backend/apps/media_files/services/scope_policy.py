"""Per-scope upload policy.

Ported as-is from ``services/media/app/core/scope_policy.py`` — pure data
plus two pure functions, no FastAPI/SQLAlchemy dependency to translate. The
module docstring below is kept close to the source; only the "later phases"
framing is dropped since this port lands all 7 policies at once (task 3.2),
not incrementally.

A ``scope`` is a high-level classification of the upload context (avatar,
chat attachment, news image, hr document, ...). It drives:

- whether the file is public or private,
- which mime types are accepted,
- the size limit,
- which thumbnail variants the worker should produce.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ScopePolicy:
    name: str
    public: bool = False
    max_mb: int | None = None  # None = fall back to global setting
    mimes: tuple[str, ...] = ()  # empty = allow all (subject to global allow-list)
    variants: tuple[str, ...] = ()


_POLICIES: dict[str, ScopePolicy] = {
    "avatar": ScopePolicy(
        name="avatar",
        public=True,
        max_mb=8,
        mimes=("image/jpeg", "image/png", "image/webp"),
        variants=("thumb_32", "thumb_96", "thumb_256"),
    ),
    "news": ScopePolicy(
        name="news",
        public=True,
        max_mb=12,
        mimes=("image/jpeg", "image/png", "image/webp"),
        variants=("thumb_256", "preview_1024"),
    ),
    "chat": ScopePolicy(
        name="chat",
        public=False,
        max_mb=50,
        mimes=(),
        variants=("thumb_256",),
    ),
    "hr_doc": ScopePolicy(
        name="hr_doc",
        public=False,
        max_mb=25,
        mimes=("application/pdf",),
        variants=(),
    ),
    "hr_department": ScopePolicy(
        name="hr_department",
        public=False,
        max_mb=50,
        mimes=(),
        variants=("thumb_256",),
    ),
    "task_attachment": ScopePolicy(
        name="task_attachment",
        public=False,
        max_mb=50,
        mimes=(),
        variants=("thumb_256",),
    ),
    "generic": ScopePolicy(
        name="generic",
        public=False,
        max_mb=None,
        mimes=(),
        variants=(),
    ),
}

KNOWN_SCOPES = frozenset(_POLICIES)


def get_policy(scope: str) -> ScopePolicy:
    """Return the policy for `scope`, or the `generic` policy if unknown."""
    return _POLICIES.get(scope, _POLICIES["generic"])


def resolve_is_public(scope: str, requested: bool | None) -> bool:
    """Decide the final `is_public` flag.

    Scope policy is authoritative when it forces public (avatar/news) — even
    if the caller forgets to set `is_public=true`. For scopes that default to
    private (chat/hr_doc/task_attachment/generic), the caller may opt-in to
    public by passing `requested=True` explicitly.
    """
    policy = get_policy(scope)
    if policy.public:
        return True
    return bool(requested) if requested is not None else False
