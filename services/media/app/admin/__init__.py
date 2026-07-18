"""sqladmin admin panel for media-service."""

from fastapi import FastAPI
from sqladmin import Admin
from sqlalchemy.ext.asyncio import AsyncEngine

from app.admin.views.file_metadata import FileMetadataAdmin
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

    admin.add_view(FileMetadataAdmin)

    return admin
