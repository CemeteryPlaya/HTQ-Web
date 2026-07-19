"""Profile business logic — get/patch profile, change password, avatar.

Ported from ``services/user/app/api/v1/profile.py`` (the FastAPI original).
Response shape (``build_response``), field-precedence rules
(``apply_profile_fields``) and the change-password rule
(``change_password``) are kept field-for-field/behaviour-for-behaviour
identical to that source — the React SPA parses the response as-is.

**Decision Р3 (the one deliberate deviation):** the FastAPI source forwards
the uploaded avatar file to media-service over an S2S JWT and stores the
URL it returns. This Django port does not do that S2S hop — it writes the
file straight to ``htqweb.storage`` (bucket ``settings.MEDIA_S3_BUCKET``)
and builds a stable signed URL itself (``htqweb.storage.signed_url``). The
endpoint that actually serves ``/api/media/v1/files/<key>`` (redirecting to
a presigned S3 URL, verifying ``sig``/``exp``) is a later task (3.3); until
then this URL is written but not yet fetchable — see the task 2.3 report.
"""

from __future__ import annotations

import json
import logging
import re
import uuid

from django.conf import settings

from htqweb.storage import get_storage, signed_query

from apps.users.models import User

logger = logging.getLogger(__name__)


class InvalidSettingsJSON(Exception):
    """``settings`` form field was present but not valid-JSON-object text."""


class CurrentPasswordRequired(Exception):
    """``current_password`` missing/wrong, and ``must_change_password`` is False."""


# UUID-shaped file id embedded in a media-service URL — ported verbatim from
# the FastAPI original's ``_FILE_ID_RE``. Our own avatar keys
# (``avatars/<user_id>/<uuid><ext>``) never match this 36-char-UUID-only
# shape, so ``avatar_payload()`` falls through to the "legacy/external URL"
# branch for every avatar this module writes — ``id`` stays ``None``,
# ``variants`` stays ``{}`` (the thumbnail worker doesn't exist in this
# port — see the module docstring / task brief).
_FILE_ID_RE = re.compile(r"/files/([0-9a-f-]{36})", re.IGNORECASE)

# Extracts the storage key *we* embedded in avatar_url, for our own
# best-effort delete of the underlying object. Distinct from _FILE_ID_RE
# above (that one exists purely for response-shape parity with the FastAPI
# source's UUID-based media-service URLs; this one is our own bookkeeping
# for the storage key format `avatars/<user_id>/<filename>`).
_AVATAR_KEY_RE = re.compile(r"^/api/media/v1/files/(.+?)(?:\?|$)")


def avatar_payload(avatar_url: str | None) -> dict | None:
    """Build the structured ``avatar`` block from a stored URL.

    Ported verbatim from the FastAPI original's ``_avatar_payload``.
    """
    if not avatar_url:
        return None
    m = _FILE_ID_RE.search(avatar_url)
    if not m:
        # Legacy / external URLs (e.g., i.pravatar.cc) — and, in this port,
        # every avatar_url we write ourselves (see module docstring).
        return {"id": None, "url": avatar_url, "variants": {}}
    file_id = m.group(1)
    return {
        "id": file_id,
        "url": f"/api/media/v1/files/{file_id}",
        "variants": {
            "thumb_32": f"/api/media/v1/files/{file_id}/thumb_32",
            "thumb_96": f"/api/media/v1/files/{file_id}/thumb_96",
            "thumb_256": f"/api/media/v1/files/{file_id}/thumb_256",
        },
    }


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
    """
    first_name = user.first_name or ""
    last_name = user.last_name or ""
    patronymic = user.patronymic or ""
    fio_parts = [p for p in (last_name, first_name, patronymic) if p]
    fio = " ".join(fio_parts)
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
        "avatar_url": user.avatar_url,
        "avatarUrl": user.avatar_url,
        "avatar": avatar_payload(user.avatar_url),
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
    ``HTTPException(400, ...)``.
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


def _avatar_key_from_url(avatar_url: str | None) -> str | None:
    if not avatar_url:
        return None
    m = _AVATAR_KEY_RE.search(avatar_url)
    return m.group(1) if m else None


# Fixed content-type -> extension allow-list for avatar uploads (review
# Finding 2). Deliberately NOT ``mimetypes.guess_extension`` (services/
# media's ``_ext_for`` uses that) — this module only ever stores images, so
# a small fixed map is both stricter and simpler than delegating to the
# stdlib's much broader (non-image-aware) mime db.
_AVATAR_CONTENT_TYPE_EXT = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
}

# Strict allow-list for the filename-tail fallback: lowercase alnum only,
# 1-8 chars. Anything else (``?``, ``&``, ``..``, ``/``, whitespace,
# uppercase) is rejected outright rather than sanitized/escaped, so it can
# never reach the storage key or the returned avatar_url.
_SAFE_EXT_TAIL_RE = re.compile(r"[a-z0-9]{1,8}")


def _safe_avatar_ext(filename: str | None, content_type: str | None) -> str:
    """Derive a safe file extension for an avatar upload key.

    Never trusts the client-supplied filename directly (review Finding 2):
    a crafted name like ``"evil.png?x=1&y=2"`` or ``"../../../etc/passwd"``
    would otherwise inject ``?``/``&``/``..`` into the S3 key AND the
    returned ``avatar_url``, and could make ``_AVATAR_KEY_RE`` mis-parse on
    a later delete (orphaning the object).

    Precedence, mirroring services/media's ``_ext_for`` intent but
    stricter: (1) the upload's content-type, mapped through a fixed
    image-only allow-list; (2) the filename tail, ONLY if it is itself a
    strict ``[a-z0-9]{1,8}`` token once lowercased; (3) ``.jpg`` as a safe
    default (documented choice — avatars are jpeg-compatible for display
    either way, and a default is required so an unrecognised/hostile input
    never falls through with no extension or a raw client string).
    """
    if content_type:
        ext = _AVATAR_CONTENT_TYPE_EXT.get(content_type.strip().lower())
        if ext:
            return ext
    if filename and "." in filename:
        tail = filename.rsplit(".", 1)[-1].lower()
        if _SAFE_EXT_TAIL_RE.fullmatch(tail):
            return "." + tail
    return ".jpg"


def save_avatar(user_id: int, filename: str, data: bytes, content_type: str | None) -> str:
    """Store the avatar directly in ``htqweb.storage`` (decision Р3).

    Raises whatever the underlying storage backend raises — callers
    (``apps.users.views.update_profile``) must catch it and degrade: save
    the rest of the profile PATCH, log the error, keep the old
    ``avatar_url``. See the task 2.3 report for why (mirrors cms's
    fire-and-forget principle for non-critical side effects).
    """
    ext = _safe_avatar_ext(filename, content_type)
    key = f"avatars/{user_id}/{uuid.uuid4().hex}{ext}"
    storage = get_storage(bucket=settings.MEDIA_S3_BUCKET)
    storage.save(key, data, content_type=content_type)
    return f"/api/media/v1/files/{key}?{signed_query(key)}"


def delete_avatar_object(avatar_url: str | None) -> None:
    """Best-effort delete of the underlying storage object.

    Mirrors the FastAPI original's best-effort media-service DELETE call in
    ``remove_avatar`` — failures are logged, never raised, so the
    user-facing detach (``user.avatar_url = None``) always succeeds even if
    the storage backend is unreachable.
    """
    key = _avatar_key_from_url(avatar_url)
    if not key:
        return
    try:
        get_storage(bucket=settings.MEDIA_S3_BUCKET).delete(key)
    except Exception as exc:  # noqa: BLE001 — best-effort cleanup only
        logger.warning("avatar_delete_storage_failed key=%s err=%s", key, exc)


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
    user.save(update_fields=["password", "must_change_password"])
