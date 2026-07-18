"""sqladmin admin panel for hr-service — mounted at /admin/."""

from fastapi import FastAPI
from sqladmin import Admin
from sqlalchemy.ext.asyncio import AsyncEngine

from app.admin.views import (
    ApplicationAdmin,
    AuditLogAdmin,
    DepartmentAdmin,
    DocumentAdmin,
    EmployeeAdmin,
    LevelThresholdAdmin,
    OrgSettingsAdmin,
    PMOAssignmentAdmin,
    PositionAdmin,
    ReportingRelationAdmin,
    ShareableLinkAdmin,
    TimeEntryAdmin,
    VacancyAdmin,
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
        EmployeeAdmin,
        DepartmentAdmin,
        PositionAdmin,
        VacancyAdmin,
        ApplicationAdmin,
        TimeEntryAdmin,
        DocumentAdmin,
        AuditLogAdmin,
        OrgSettingsAdmin,
        PMOAssignmentAdmin,
        ReportingRelationAdmin,
        ShareableLinkAdmin,
        LevelThresholdAdmin,
    ):
        admin.add_view(view)
    return admin
