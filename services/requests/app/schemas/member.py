from datetime import datetime

from pydantic import BaseModel

from app.models.project_member import ProjectMemberRole


class MemberAdd(BaseModel):
    user_id: int
    role: ProjectMemberRole = ProjectMemberRole.MEMBER


class MemberResponse(BaseModel):
    project_id: int
    user_id: int
    role: ProjectMemberRole
    granted_by: int | None = None
    granted_at: datetime

    model_config = {"from_attributes": True}
