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

import logging
from dataclasses import dataclass

from django.core.exceptions import PermissionDenied

logger = logging.getLogger(__name__)


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
    # Документ, приложенный к решению согласующего (apps.signoff). PDF-only
    # by policy rather than by a mime check inside signoff: restricting
    # ``mimes`` here also turns on ``upload_service._validate_signature``,
    # so a caller can't POST arbitrary bytes under ``Content-Type:
    # application/pdf`` — the same deal ``hr_doc`` gets. Not in
    # RESTRICTED_SCOPES: signoff authorizes the write by task ownership
    # (only the assigned approver can attach), which is an ownership rule,
    # not the elevated-role gate that flag is for.
    "signoff_doc": ScopePolicy(
        name="signoff_doc",
        public=False,
        max_mb=25,
        mimes=("application/pdf",),
        variants=(),
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


def normalize_scope(raw: str | None) -> str:
    """Canonicalise a client-supplied scope string: strip surrounding
    whitespace and lowercase it.

    ``scope`` is free-text client input used for authorization
    (``authorize_scope_write``), policy lookup (``get_policy``), the storage
    path (``upload_service._build_path``) and the stored ``FileMetadata.scope``.
    Without normalization a case/whitespace variant of a restricted scope
    (``"HR_DOC"``, ``"hr_doc "``) would miss the exact-match ``RESTRICTED_SCOPES``
    / ``KNOWN_SCOPES`` checks and slip through the unknown→generic branch, then
    be stored verbatim — so a future hr/task READ side matching the canonical
    string would either mis-classify it or (worse, if it matched loosely) grant
    privileged access. Normalizing at every consumer closes that at the source:
    the canonical form is the only thing authorized, looked up, and stored.
    """
    return (raw or "").strip().lower()


def get_policy(scope: str) -> ScopePolicy:
    """Return the policy for `scope`, or the `generic` policy if unknown."""
    return _POLICIES.get(normalize_scope(scope), _POLICIES["generic"])


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


# ─── R5 — scope write-authorization seam (decision Д1) ─────────────────────
#
# ``scope`` is free-text, unauthorized client input (see ``views.upload_file``
# and ``interface.store_file``) — before this seam, ANY authenticated caller
# could write into ``hr_doc``/``hr_department``/``task_attachment``, three
# scopes that belong to not-yet-migrated privileged/owned domains. Nothing
# reads by scope yet, so this was unexploited, but the fork had to be closed
# before hr/task land.
#
# RESTRICTED_SCOPES is deliberately just the three not-yet-migrated domains.
# Everything else (``avatar``, ``news``, ``chat``, ``generic``) is already
# effectively user-writable in practice — ``news`` covers go through admin
# news endpoints, ``chat``/``avatar``/``generic`` are ordinary user content —
# so no extra check is added for them here.
RESTRICTED_SCOPES = frozenset({"hr_doc", "hr_department", "task_attachment"})


def authorize_scope_write(scope: str, *, is_elevated: bool) -> None:
    """Authorize writing (uploading) into ``scope``. Raises
    ``django.core.exceptions.PermissionDenied`` (→ 403 via ``api_view``) to
    deny; returns ``None`` to allow.

    **Interim rule (decision Д1) — NOT the final model.** ``hr_doc``,
    ``hr_department``, and ``task_attachment`` belong to domains that have
    not migrated yet (hr/task, phases 4/6). Until they do, there is no real
    HR-role / task-membership / ownership check to enforce, so this is a
    conservative default-deny: only ``is_elevated`` (platform admin/staff)
    callers may write these scopes. When hr/task migrate, THEY are expected
    to refine this into real role/ownership checks via their own
    ``interface`` calls (or a per-scope predicate registered here) — this
    function is the one seam both entry points (the HTTP upload view and
    ``interface.store_file``) call, so that refinement lands in one place,
    not three.

    Any scope not in ``RESTRICTED_SCOPES`` — including the open scopes
    (``avatar``/``news``/``chat``/``generic``) and any UNKNOWN scope not in
    ``KNOWN_SCOPES`` (e.g. the frontend's ``cms-news``, see
    ``get_policy``) — is open to any authenticated caller: no check here.
    An unknown scope is logged loudly (it silently fell back to the
    ``generic`` *policy* already via ``get_policy``; this is the write-auth
    side of that same fallback) rather than rejected, so pre-existing
    frontend behaviour (``scope=cms-news`` for inline news images) keeps
    working.
    """
    scope = normalize_scope(scope)
    if scope not in KNOWN_SCOPES:
        logger.warning("unknown upload scope %r, falling back to generic", scope)
        return

    if scope in RESTRICTED_SCOPES and not is_elevated:
        raise PermissionDenied(
            f"scope '{scope}' is restricted to elevated (staff/admin) callers "
            f"until its owning domain migrates and defines real role/ownership "
            f"rules (decision Д1)"
        )
