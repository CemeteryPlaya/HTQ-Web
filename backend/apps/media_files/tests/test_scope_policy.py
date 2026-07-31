"""Contract test for the ported ``ScopePolicy`` table (task 3.2).

Values asserted against ``services/media/app/core/scope_policy.py`` (the
FastAPI source) — this is a straight data-parity check, no Django/DB
involved.
"""

from apps.media_files.services.scope_policy import (
    KNOWN_SCOPES,
    get_policy,
    resolve_is_public,
)


def test_known_scopes_are_the_seven_source_scopes_plus_post_migration_ones():
    """The seven ported scopes, plus every scope added after the cutover.

    ``signoff_doc`` has no FastAPI ancestor — ``apps.signoff`` post-dates the
    migration entirely — so it is listed separately from the parity set
    rather than folded into it.
    """
    ported = {"avatar", "news", "chat", "hr_doc", "hr_department",
              "task_attachment", "generic"}
    added_after_cutover = {"signoff_doc"}

    assert KNOWN_SCOPES == ported | added_after_cutover


def test_signoff_doc_policy():
    """PDF-only and private: it holds the document a named approver signed
    (``apps.signoff``, ``ApprovalTask.file_id``). Restricting ``mimes`` is
    also what turns on the magic-byte check in ``upload_service``."""
    p = get_policy("signoff_doc")
    assert p.public is False
    assert p.max_mb == 25
    assert p.mimes == ("application/pdf",)
    assert p.variants == ()


def test_avatar_policy():
    p = get_policy("avatar")
    assert p.public is True
    assert p.max_mb == 8
    assert p.mimes == ("image/jpeg", "image/png", "image/webp")
    assert p.variants == ("thumb_32", "thumb_96", "thumb_256")


def test_news_policy():
    p = get_policy("news")
    assert p.public is True
    assert p.max_mb == 12
    assert p.mimes == ("image/jpeg", "image/png", "image/webp")
    assert p.variants == ("thumb_256", "preview_1024")


def test_chat_policy():
    p = get_policy("chat")
    assert p.public is False
    assert p.max_mb == 50
    assert p.mimes == ()
    assert p.variants == ("thumb_256",)


def test_hr_doc_policy():
    p = get_policy("hr_doc")
    assert p.public is False
    assert p.max_mb == 25
    assert p.mimes == ("application/pdf",)
    assert p.variants == ()


def test_hr_department_policy():
    p = get_policy("hr_department")
    assert p.public is False
    assert p.max_mb == 50
    assert p.mimes == ()
    assert p.variants == ("thumb_256",)


def test_task_attachment_policy():
    p = get_policy("task_attachment")
    assert p.public is False
    assert p.max_mb == 50
    assert p.mimes == ()
    assert p.variants == ("thumb_256",)


def test_generic_policy():
    p = get_policy("generic")
    assert p.public is False
    assert p.max_mb is None
    assert p.mimes == ()
    assert p.variants == ()


def test_get_policy_unknown_scope_falls_back_to_generic():
    p = get_policy("this-scope-does-not-exist")
    assert p is get_policy("generic")


def test_resolve_is_public_forces_true_for_public_scopes_even_if_not_requested():
    assert resolve_is_public("avatar", None) is True
    assert resolve_is_public("avatar", False) is True
    assert resolve_is_public("news", False) is True


def test_resolve_is_public_defaults_false_for_private_scopes():
    assert resolve_is_public("generic", None) is False
    assert resolve_is_public("chat", None) is False


def test_resolve_is_public_allows_opt_in_for_private_scopes():
    assert resolve_is_public("chat", True) is True
    assert resolve_is_public("generic", True) is True
    assert resolve_is_public("generic", False) is False
