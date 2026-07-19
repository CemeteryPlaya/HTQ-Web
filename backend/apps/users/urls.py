from django.urls import path

from . import views

urlpatterns = [
    # token/, token/refresh/ — frontend call sites (frontend/src/api/users.ts,
    # frontend/src/api/client.ts) both send a trailing slash; APPEND_SLASH=False
    # means Django never adds one on its own, so only these exact spellings
    # are registered (no bare-no-slash alias needed, unlike the cms app's
    # detail routes — nothing in the frontend calls these without one).
    path("token/", views.obtain_token),
    path("token/refresh/", views.refresh_token),
    # admin-session/login, admin-session/logout — posted by sqladmin's own
    # login page (server-rendered HTML form), not the SPA; the FastAPI
    # original registers these WITHOUT a trailing slash
    # (services/user/app/api/v1/auth.py's admin_router), so that's the only
    # spelling registered here too.
    path("admin-session/login", views.admin_login),
    path("admin-session/logout", views.admin_logout),
    # profile/me + profile/ alias — confirmed frontend call sites use
    # 'profile/me' (frontend/src/api/users.ts, useActiveProfile.ts,
    # Settings.tsx, MyProfile.tsx, ConferencePage.tsx, hr/*.tsx); '/' alias
    # kept for source parity (services/user/app/api/v1/profile.py registers
    # both) even though nothing in the SPA calls it today.
    path("profile/me", views.profile_me),
    path("profile/", views.profile_me),
    # change-password/ — frontend calls WITH a trailing slash
    # (Settings.tsx, ForcePasswordChange.tsx); bare spelling kept for parity
    # with the FastAPI source's dual @router.post registration.
    path("profile/change-password", views.change_password),
    path("profile/change-password/", views.change_password),
    path("profile/avatar", views.remove_avatar),
    path("profile/avatar/", views.remove_avatar),
]
