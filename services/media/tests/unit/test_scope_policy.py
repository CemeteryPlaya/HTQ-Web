"""Scope policy: per-context upload limits + visibility resolution."""

from app.core.scope_policy import KNOWN_SCOPES, get_policy, resolve_is_public


def test_known_scopes_include_avatar_news_chat_hr_doc_generic():
    expected = {"avatar", "news", "chat", "hr_doc", "task_attachment", "generic"}
    assert expected.issubset(KNOWN_SCOPES)


def test_avatar_policy_is_public_image_only_capped_at_8mb():
    p = get_policy("avatar")
    assert p.public is True
    assert p.max_mb == 8
    assert "image/jpeg" in p.mimes
    assert "image/png" in p.mimes
    assert "image/webp" in p.mimes
    assert "thumb_32" in p.variants
    assert "thumb_96" in p.variants
    assert "thumb_256" in p.variants


def test_news_is_public():
    assert get_policy("news").public is True


def test_chat_and_hr_doc_are_private():
    assert get_policy("chat").public is False
    assert get_policy("hr_doc").public is False


def test_unknown_scope_falls_back_to_generic():
    assert get_policy("does-not-exist").name == "generic"


def test_resolve_is_public_avatar_always_public_even_when_caller_says_no():
    # Avatar policy is authoritative — even an explicit False is upgraded.
    assert resolve_is_public("avatar", requested=False) is True
    assert resolve_is_public("avatar", requested=None) is True


def test_resolve_is_public_chat_respects_caller():
    assert resolve_is_public("chat", requested=False) is False
    assert resolve_is_public("chat", requested=None) is False
    # Chat starts private; an explicit opt-in is honoured (e.g. shareable link).
    assert resolve_is_public("chat", requested=True) is True


def test_resolve_is_public_generic_defaults_to_private():
    assert resolve_is_public("generic", requested=None) is False
