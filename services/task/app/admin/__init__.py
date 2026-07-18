"""sqladmin admin panel for task-service — mounted at /admin/."""

from fastapi import FastAPI
from sqladmin import Admin
from sqlalchemy.ext.asyncio import AsyncEngine

from app.admin.views import (
    LabelAdmin,
    NotificationAdmin,
    ProductionDayAdmin,
    ProjectAdmin,
    TaskActivityAdmin,
    TaskAdmin,
    TaskAttachmentAdmin,
    TaskCommentAdmin,
    TaskLinkAdmin,
    TaskSequenceAdmin,
    TaskTypeAdmin,
)
from app.auth.admin_backend import JWTAdminAuthBackend
from app.core.settings import settings


def create_admin(app: FastAPI, engine: AsyncEngine) -> Admin:
    admin = Admin(
        app=app,
        engine=engine,
        base_url="/sqladmin",
        title=f"{settings.service_name} admin",
        authentication_backend=JWTAdminAuthBackend(secret_key=settings.jwt_secret),
    )
    for view in (
        TaskAdmin,
        TaskCommentAdmin,
        TaskAttachmentAdmin,
        TaskLinkAdmin,
        TaskActivityAdmin,
        LabelAdmin,
        ProjectAdmin,
        TaskTypeAdmin,
        NotificationAdmin,
        TaskSequenceAdmin,
        ProductionDayAdmin,
    ):
        admin.add_view(view)
    return admin
