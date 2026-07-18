"""sqladmin admin panel — per-service admin UI mounted at /admin/.

Wire it up in main.py:

    from app.admin import create_admin
    from app.db import engine
    create_admin(app, engine)

ModelViews live in app/admin/views/ and are registered inside create_admin().
The auth backend (cookie-based JWT with is_admin claim) lives in
app/auth/admin_backend.py.
"""

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine
from sqladmin import Admin

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

    # Register ModelViews here (one import per model file in app/admin/views/):
    # from app.admin.views.example import ExampleAdmin
    # admin.add_view(ExampleAdmin)

    return admin
