from sqladmin import Admin
from app.auth.backend import JWTAdminAuthBackend
from app.core.logging import get_logger
from app.core.settings import settings
from app.db import engine

log = get_logger(__name__)

def create_admin(app):
    admin = Admin(app=app, engine=engine, base_url="/sqladmin",
                  title="HTQWeb Central Admin",
                  authentication_backend=JWTAdminAuthBackend(secret_key=settings.jwt_secret))

    _try_register(admin, "user.app.admin.views", ["UserAdmin"])
    _try_register(admin, "cms.app.admin", ["NewsAdmin", "ContactRequestAdmin"])
    _try_register(admin, "media.app.admin.views", ["FileMetadataAdmin"])
    _try_register(admin, "messenger.app.admin.views",
                  ["ChatUserReplicaAdmin", "RoomAdmin", "RoomParticipantAdmin",
                   "MessageAdmin", "UserKeyAdmin", "MessageAttachmentAdmin"])
    _try_register(admin, "email.app.admin.views",
                  ["EmailMessageAdmin", "EmailRecipientStatusAdmin",
                   "EmailAttachmentAdmin", "EmailOAuthTokenAdmin"])
    _try_register(admin, "hr.app.admin.views", ["EmployeeAdmin", "DepartmentAdmin", "PositionAdmin"])
    _try_register(admin, "task.app.admin.views", ["TaskAdmin", "TaskCommentAdmin", "TaskAttachmentAdmin", "LabelAdmin", "ProjectVersionAdmin"])
    
    return admin

def _try_register(admin, module_path: str, view_names: list[str]) -> None:
    try:
        mod = __import__(module_path, fromlist=view_names)
        for name in view_names:
            view_class = getattr(mod, name)
            admin.add_view(view_class)
        log.info("admin_views_registered", module=module_path, count=len(view_names))
    except Exception as e:
        log.warning("admin_views_import_failed", module=module_path, error=str(e))
