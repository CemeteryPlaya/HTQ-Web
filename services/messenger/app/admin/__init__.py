"""sqladmin admin panel for messenger-service."""

from sqladmin import Admin

from app.auth.admin_backend import JWTAdminAuthBackend
from app.core.settings import settings
from app.admin.views import (
    ChatUserReplicaAdmin, RoomAdmin, RoomParticipantAdmin,
    MessageAdmin, UserKeyAdmin, ChatAttachmentAdmin,
)

def create_admin(app, engine):
    admin = Admin(app=app, engine=engine, base_url="/sqladmin",
                  authentication_backend=JWTAdminAuthBackend(secret_key=settings.jwt_secret))
    for view in (ChatUserReplicaAdmin, RoomAdmin, RoomParticipantAdmin,
                 MessageAdmin, UserKeyAdmin, ChatAttachmentAdmin):
        admin.add_view(view)
    return admin
