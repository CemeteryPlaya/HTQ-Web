"""Profile business logic — get/patch profile, change password, avatar.

Ported from ``services/user/app/api/v1/profile.py`` (the FastAPI original).
Response shape (``build_response``), field-precedence rules
(``apply_profile_fields``) and the change-password rule
(``change_password``) are kept field-for-field/behaviour-for-behaviour
identical to that source — the React SPA parses the response as-is.

**Avatar storage — history and the final-review-of-phases-2-3 fix.**
Task 2.3's decision Р3 was: instead of the FastAPI source's S2S forward to
media-service, write the avatar straight to ``htqweb.storage`` and mint a
long-lived signed URL (``htqweb.storage.signed_url``) *once*, at upload
time, then persist that whole URL — signature and all — in
``User.avatar_url`` forever. Two problems fell out of that, both closed
here:

1. **(Critical)** the persisted URL's signature expires
   (``settings.NEWS_SIGNED_URL_TTL``, default 1h) and nothing ever
   re-signs it — every avatar went dead an hour after upload with no
   refresh path. Fixed by never persisting a signature: ``User.avatar_url``
   now stores the *unsigned* canonical path
   (``/api/media/v1/files/<file_id>``), and ``avatar_payload``/
   ``build_response`` mint a fresh URL on every response via
   ``apps.media_files.interface.get_file_url`` — which returns that same
   plain path untouched for a public file, or a freshly-signed one for a
   private file. Either way, a response handed to the browser is always
   currently valid.
2. **(Important)** the direct-to-storage write bypassed
   ``apps.media_files.services.scope_policy.ScopePolicy`` entirely — no
   size cap, no real mime allow-list (only the *filename extension* was
   checked), no magic-byte signature check, no EXIF strip/re-encode, and
   the client's declared ``content_type`` was trusted straight through to
   the storage backend. It also meant the ``media`` kill-switch
   (``apps.core.services.require_service``) never even ran for avatars.
   Fixed by routing ``save_avatar`` through
   ``apps.media_files.interface.store_file(scope="avatar", ...)`` — the
   exact same pipeline ``POST /api/media/v1/files/`` uses. ``users``
   importing ``apps.media_files.interface`` is the sanctioned way for one
   app to reach another (see that module's docstring); this is not a
   layering violation.

One consequence of (2) worth calling out: the ``avatar`` scope
(``apps.media_files.services.scope_policy``) is ``public=True``, so every
avatar written through this path is a public ``FileMetadata`` row —
``get_file_url`` never needs to sign it at all in practice. The
sign-at-read-time machinery in ``avatar_payload``/``build_response`` still
exists and is exercised (it is the only thing standing between "works
today" and "silently breaks the day someone flips the avatar scope to
private"), but for the current policy it's mostly future-proofing, not
something visibly exercised by the happy path.

Pre-existing rows written by the old code path (raw storage key,
signature baked into the URL) are **not** migrated by this change — they
still match the legacy branch below (``_FILE_ID_RE`` doesn't recognise a
raw ``avatars/<user_id>/<uuid><ext>`` key) and will keep serving/expiring
exactly as before until the user re-uploads. No such rows exist outside
this repo's own test fixtures at the time of this fix (see the final
review report for the full inventory), so no data migration was written.
"""

from __future__ import annotations

import json
import logging
import re

from apps.users.models import User

logger = logging.getLogger(__name__)


class InvalidSettingsJSON(Exception):
    """``settings`` form field was present but not valid-JSON-object text."""


class CurrentPasswordRequired(Exception):
    """``current_password`` missing/wrong, and ``must_change_password`` is False."""


class FieldTooLong(Exception):
    """A form field exceeded its column width.

    Without this the value goes straight into a ``varchar(N)`` column and
    Postgres answers with a ``DataError`` — i.e. a 500 for what is plainly a
    bad request. The frontend's masked inputs never send anything this long
    (``PhoneInput`` caps a number at ``+7 (700) 483-55-81``); this is the
    guard for everything that does not go through them.
    """


# UUID-shaped file id embedded in a media-service URL — ported verbatim from
# the FastAPI original's ``_FILE_ID_RE``. Since the final-review fix
# (Findings 1/2), every avatar this module writes IS a FileMetadata row and
# DOES match this shape (``/api/media/v1/files/<uuid>``, no signature baked
# in — see the module docstring). Pre-fix rows using the old raw-key shape
# (``avatars/<user_id>/<uuid><ext>``, with ``?sig=&exp=``) never match it
# and fall through to the legacy/external-URL branch below, same as a
# genuinely external URL (e.g. i.pravatar.cc) would.
_FILE_ID_RE = re.compile(r"/files/([0-9a-f-]{36})", re.IGNORECASE)

_AVATAR_VARIANTS = ("thumb_32", "thumb_96", "thumb_256")


def avatar_payload(avatar_url: str | None) -> dict | None:
    """Build the structured ``avatar`` block from a stored URL.

    Ported from the FastAPI original's ``_avatar_payload``, extended by the
    final review of phases 2-3 (Finding 1 — CRITICAL) to mint the URL(s)
    fresh on *every* call rather than echo back whatever was persisted:
    ``User.avatar_url`` only ever stores the bare, unsigned canonical path
    now (see ``save_avatar``); the actual signed-vs-plain decision is made
    here, per response, via ``apps.media_files.interface.get_file_url`` —
    so a client is never handed a URL whose signature has already expired
    by the time it's read back. ``users`` importing
    ``apps.media_files.interface`` is the sanctioned cross-app seam, not a
    layering violation (see that module's docstring).
    """
    if not avatar_url:
        return None
    m = _FILE_ID_RE.search(avatar_url)
    if not m:
        # Legacy raw-key rows (pre-fix, see module docstring) and genuinely
        # external URLs (e.g. i.pravatar.cc) — nothing of ours to re-sign,
        # pass through untouched.
        return {"id": None, "url": avatar_url, "variants": {}}
    file_id = m.group(1)

    from apps.media_files import interface as media_interface

    def _fresh(variant: str) -> str | None:
        try:
            return media_interface.get_file_url(file_id, variant=variant)
        except Exception:
            # ServiceDisabled (media off) or any other hiccup minting a
            # fresh URL — degrade rather than fail the whole profile
            # response over a picture. Falls back to the stored (unsigned)
            # path for the primary URL; variants simply get omitted.
            return None

    url = _fresh("original") or avatar_url
    variants = {name: u for name in _AVATAR_VARIANTS if (u := _fresh(name))}

    return {"id": file_id, "url": url, "variants": variants}


def roles_for(user: User) -> list[str]:
    roles: list[str] = []
    if user.is_superuser:
        roles.append("admin")
    if user.is_staff and not user.is_superuser:
        roles.append("staff")
    if not roles:
        roles.append("user")
    return roles


def build_response(user: User) -> dict:
    """Ported field-for-field from the FastAPI original's ``_build_response``.

    Returned as a plain dict (not a pydantic model) — ``htqweb.http.api_view``
    JSON-serializes dicts directly, and a dict lets ``avatar``/``settings``
    nest freely without a schema class per call site.

    ``avatar_url``/``avatarUrl`` are derived from the same freshly-minted
    ``avatar_payload()`` call as the nested ``avatar.url`` (final review of
    phases 2-3, Finding 1) rather than echoing ``user.avatar_url`` raw —
    both top-level and nested shapes must agree, and both must be
    currently-valid, not whatever was persisted at upload time.
    """
    first_name = user.first_name or ""
    last_name = user.last_name or ""
    patronymic = user.patronymic or ""
    fio_parts = [p for p in (last_name, first_name, patronymic) if p]
    fio = " ".join(fio_parts)
    avatar = avatar_payload(user.avatar_url)
    avatar_url = avatar["url"] if avatar else None
    return {
        "id": str(user.id),
        "username": user.username,
        "email": user.email,
        "first_name": first_name,
        "last_name": last_name,
        "firstName": first_name,
        "lastName": last_name,
        "patronymic": patronymic,
        "display_name": user.display_name or "",
        "fio": fio,
        "bio": user.bio or "",
        "phone": user.phone or "",
        "avatar_url": avatar_url,
        "avatarUrl": avatar_url,
        "avatar": avatar,
        "settings": user.settings or {},
        "roles": roles_for(user),
        "department": None,
        "department_id": None,
        "position": None,
        "must_change_password": bool(user.must_change_password),
        "date_joined": user.date_joined.isoformat() if user.date_joined else None,
        "last_login": user.last_login.isoformat() if user.last_login else None,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "updated_at": user.updated_at.isoformat() if user.updated_at else None,
    }


def apply_profile_fields(
    user: User,
    *,
    display_name: str | None,
    first_name: str | None,
    last_name: str | None,
    patronymic: str | None,
    bio: str | None,
    phone: str | None,
    settings_json: str | None,
) -> dict:
    """Mutate ``user`` in place per the PATCH precedence rules.

    Callers are responsible for coalescing the camelCase/snake_case aliases
    BEFORE calling this (``first_name``/``last_name`` here are already the
    "effective" values — ``firstName if firstName is not None else
    first_name``, ported verbatim from the FastAPI original). Returns a
    dict of changed field names (for logging parity), same shape as the
    source's ``changes``.

    Raises ``InvalidSettingsJSON`` if ``settings_json`` is present but not
    valid-JSON-object text — callers map that to a 400, same as the source's
    ``HTTPException(400, ...)``. Raises ``FieldTooLong`` when a value would
    overflow its column (also a 400 — see that exception's docstring).
    """
    changes: dict = {}

    for field, value in [
        ("display_name", display_name),
        ("first_name", first_name),
        ("last_name", last_name),
        ("patronymic", patronymic),
        ("bio", bio),
        ("phone", phone),
    ]:
        if value is not None:
            limit = User._meta.get_field(field).max_length
            if limit is not None and len(value) > limit:
                raise FieldTooLong(f"{field} must be at most {limit} characters")
        if value is not None and getattr(user, field, None) != value:
            changes[field] = value
            setattr(user, field, value)

    if settings_json is not None:
        try:
            parsed = json.loads(settings_json) if settings_json else {}
        except json.JSONDecodeError as exc:
            raise InvalidSettingsJSON("settings must be valid JSON") from exc
        if not isinstance(parsed, dict):
            raise InvalidSettingsJSON("settings must be a JSON object")
        if parsed != (user.settings or {}):
            changes["settings"] = "updated"
            user.settings = parsed

    return changes


def save_avatar(user_id: int, filename: str, data: bytes, content_type: str | None) -> str:
    """Store the avatar through the real media pipeline.

    Final review of phases 2-3 (Finding 2 — Important): this used to write
    straight to ``htqweb.storage`` with only a filename-extension allow-list
    of its own, bypassing ``ScopePolicy`` (size cap, real mime allow-list,
    magic-byte signature check, EXIF strip/re-encode) and the ``media``
    kill-switch entirely. Now it calls
    ``apps.media_files.interface.store_file(scope="avatar", ...)`` — the
    exact same pipeline the ``POST /api/media/v1/files/`` endpoint runs —
    so every one of those checks actually applies, and a disabled ``media``
    service correctly refuses the write (``ServiceDisabled``) instead of
    silently succeeding.

    Returns the unsigned canonical path (``result["url"]``, e.g.
    ``/api/media/v1/files/<uuid>``) — never a signature, see the module
    docstring's Finding 1 section for why. Raises whatever
    ``store_file`` raises (``ServiceDisabled`` when ``media`` is off,
    ``UploadValidationError`` for oversize/wrong-mime/undecodable-image) —
    callers (``apps.users.views._update_profile``) must catch it and
    degrade: save the rest of the profile PATCH, log the error, keep the
    old ``avatar_url``. See the task 2.3 report for why (mirrors cms's
    fire-and-forget principle for non-critical side effects) — that
    degradation contract is unchanged by this fix, only *what* can now
    raise (validation/kill-switch errors, not just storage-backend errors)
    is different.
    """
    from apps.media_files import interface as media_interface

    result = media_interface.store_file(
        data=data,
        filename=filename or "avatar",
        mime=content_type or "application/octet-stream",
        scope="avatar",
        owner_id=user_id,
    )
    return result["url"]


def delete_avatar_object(avatar_url: str | None) -> None:
    """Best-effort delete of the underlying avatar file.

    Mirrors the FastAPI original's best-effort media-service DELETE call in
    ``remove_avatar`` — failures are logged, never raised, so the
    user-facing detach (``user.avatar_url = None``) always succeeds even if
    ``media`` is unreachable or disabled.

    Since Finding 2's fix, an avatar written by this module is a real
    ``FileMetadata`` row, so this soft-deletes it via
    ``apps.media_files.interface.delete_file`` rather than touching storage
    directly. Legacy pre-fix rows (raw storage key, no ``FileMetadata``) —
    or an already-cleared/never-set ``avatar_url`` — don't match
    ``_FILE_ID_RE`` and are silently skipped, same "nothing to do" contract
    as before.
    """
    m = _FILE_ID_RE.search(avatar_url) if avatar_url else None
    if not m:
        return
    file_id = m.group(1)
    from apps.media_files import interface as media_interface

    try:
        media_interface.delete_file(file_id)
    except Exception as exc:  # noqa: BLE001 — best-effort cleanup only
        logger.warning("avatar_delete_failed file_id=%s err=%s", file_id, exc)


def change_password(user: User, *, new_password: str, current_password: str | None) -> None:
    """``POST profile/change-password``.

    Ported verbatim from the FastAPI original's rule: if
    ``must_change_password`` is set (forced reset), ``current_password`` is
    optional; otherwise it must be present and match the stored hash, or
    ``CurrentPasswordRequired`` is raised (-> 400 at the view layer, same
    status as the source).
    """
    if not user.must_change_password:
        if not current_password or not user.check_password(current_password):
            raise CurrentPasswordRequired()

    user.set_password(new_password)
    user.must_change_password = False
    # auto_now fields are NOT auto-added to a partial update_fields save —
    # updated_at must be listed explicitly (R6 Fix 2).
    user.save(update_fields=["password", "must_change_password", "updated_at"])
