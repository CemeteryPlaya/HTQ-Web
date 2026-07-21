"""Per-template behaviour switches, stored inside ``config_json.settings``.

Ported from ``services/requests/app/services/template_settings.py``. These
decide whether a request can be revoked, whether an approver may recall their
own decision, and how repeat approvers are de-duplicated — so a missing key
must fall back to the documented default rather than to ``None``, which is
why every read goes through ``{**DEFAULTS, **stored}``.
"""

from __future__ import annotations

from ..models import RequestFormTemplate

DEFAULTS: dict = {
    "allow_revoke_pending": True,
    "allow_revoke_within_days": False,
    "revoke_within_days": 0,
    "allow_modify_approved": False,
    "modify_within_days": 0,
    "allow_delegate_submission": False,
    "allow_batch": False,
    "allow_recall_decision": False,
    # none | once_auto | consecutive_auto — see request_runtime._assign_node.
    "dedup": "none",
    "exclude_efficiency": False,
}


def settings_for_template(template_id: int) -> dict:
    template = RequestFormTemplate.objects.filter(pk=template_id).first()
    stored = (template.config_json or {}).get("settings", {}) if template else {}
    return {**DEFAULTS, **(stored or {})}


def settings_for_instance(instance) -> dict:
    return settings_for_template(instance.template_id)
