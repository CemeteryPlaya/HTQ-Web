"""sqladmin admin panel for email-service."""

from fastapi import FastAPI
from sqladmin import Admin
from sqlalchemy.ext.asyncio import AsyncEngine

from app.admin.views import EmailMessageAdmin, OAuthTokenAdmin, RecipientStatusAdmin
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

    admin.add_view(OAuthTokenAdmin)
    admin.add_view(EmailMessageAdmin)
    admin.add_view(RecipientStatusAdmin)

    return admin
