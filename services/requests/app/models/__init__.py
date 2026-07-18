"""Model registry — import every model so Alembic autogenerate sees them."""

from app.models.base import Base, BaseModel
from app.models.user_replica import RequestUser
from app.models.department_replica import RequestDepartment
from app.models.project import RequestProject, ProjectStatus
from app.models.project_member import RequestProjectMember, ProjectMemberRole
from app.models.form_template import RequestFormTemplate, RequestFormTemplateVersion
from app.models.request_instance import RequestInstance, RequestStatus
from app.models.approval_action import ApprovalAction, ApprovalActionType
from app.models.request_activity import RequestActivity
from app.models.request_watcher import RequestWatcher
from app.models.notifications_log import NotificationsLog
from app.models.stats_daily import RequestStatsDaily
from app.models.reference_source import RequestReferenceSource, RequestReferenceRow

__all__ = [
    "Base", "BaseModel",
    "RequestUser", "RequestDepartment",
    "RequestProject", "ProjectStatus",
    "RequestProjectMember", "ProjectMemberRole",
    "RequestFormTemplate", "RequestFormTemplateVersion",
    "RequestInstance", "RequestStatus",
    "ApprovalAction", "ApprovalActionType",
    "RequestActivity", "RequestWatcher",
    "NotificationsLog",
    "RequestStatsDaily",
    "RequestReferenceSource", "RequestReferenceRow",
]
