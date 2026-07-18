from sqlalchemy.ext.asyncio import AsyncSession
from app.models.form_template import RequestFormTemplate
from app.models.request_instance import RequestInstance

DEFAULTS: dict = {
    "allow_revoke_pending": True,
    "allow_revoke_within_days": False,
    "revoke_within_days": 0,
    "allow_modify_approved": False,
    "modify_within_days": 0,
    "allow_delegate_submission": False,
    "allow_batch": False,
    "allow_recall_decision": False,
    "dedup": "none",
    "exclude_efficiency": False,
}


async def settings_for_template(session: AsyncSession, template_id: int) -> dict:
    tpl = await session.get(RequestFormTemplate, template_id)
    stored = (tpl.config_json or {}).get("settings", {}) if tpl else {}
    return {**DEFAULTS, **(stored or {})}


async def settings_for_instance(session: AsyncSession, inst: RequestInstance) -> dict:
    return await settings_for_template(session, inst.template_id)
