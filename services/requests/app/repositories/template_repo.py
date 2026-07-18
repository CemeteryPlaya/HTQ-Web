"""Form template + version data access."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.form_template import RequestFormTemplate, RequestFormTemplateVersion
from app.repositories.base_repo import BaseRepository


class TemplateRepository(BaseRepository[RequestFormTemplate]):
    def __init__(self, session: AsyncSession):
        super().__init__(RequestFormTemplate, session)

    async def list_for_project(self, project_id: int | None) -> list[RequestFormTemplate]:
        stmt = select(RequestFormTemplate).where(
            RequestFormTemplate.project_id == project_id,
            RequestFormTemplate.status != "deleted",  # soft-deleted templates are hidden
        )
        stmt = stmt.order_by(RequestFormTemplate.created_at.desc())
        return list((await self.session.execute(stmt)).scalars().all())

    async def slug_exists(self, project_id: int | None, slug: str) -> bool:
        stmt = select(func.count()).select_from(RequestFormTemplate).where(
            RequestFormTemplate.project_id == project_id, RequestFormTemplate.slug == slug
        )
        return (await self.session.execute(stmt)).scalar_one() > 0

    async def next_version_number(self, template_id: int) -> int:
        stmt = select(func.coalesce(func.max(RequestFormTemplateVersion.version), 0)).where(
            RequestFormTemplateVersion.template_id == template_id
        )
        return int((await self.session.execute(stmt)).scalar_one()) + 1

    async def get_version(self, version_id: int) -> RequestFormTemplateVersion | None:
        return await self.session.get(RequestFormTemplateVersion, version_id)

    async def add_version(
        self, template: RequestFormTemplate, schema_json: dict, workflow_json: dict, published_by: int | None
    ) -> RequestFormTemplateVersion:
        version = RequestFormTemplateVersion(
            template_id=template.id,
            version=await self.next_version_number(template.id),
            schema_json=schema_json,
            workflow_json=workflow_json,
            published_by=published_by,
        )
        self.session.add(version)
        await self.session.flush()
        template.current_version_id = version.id
        await self.session.flush()
        return version
