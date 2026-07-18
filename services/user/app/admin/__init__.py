"""sqladmin admin panel for user-service — mounted at /admin/."""

from fastapi import FastAPI
from sqladmin import Admin
from sqlalchemy.ext.asyncio import AsyncEngine

from app.admin.views.item import ItemAdmin
from app.admin.views.user import UserAdmin, PendingRegistrationAdmin
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

    admin.add_view(UserAdmin)
    admin.add_view(PendingRegistrationAdmin)
    admin.add_view(ItemAdmin)

    return admin
