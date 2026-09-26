"""Маршруты /api/notifications/v1/."""

from django.urls import path

from . import views

urlpatterns = [
    path("notifications", views.feed),
    path("notifications/", views.feed),
    path("notifications/history", views.feed_history),
    path("notifications/history/", views.feed_history),
    path("notifications/read-all", views.read_all),
    path("notifications/read-all/", views.read_all),
    path("notifications/<str:notification_id>/read", views.read_one),
    path("notifications/<str:notification_id>/read/", views.read_one),
    path("notifications/<str:notification_id>/unread", views.unread_one),
    path("notifications/<str:notification_id>/unread/", views.unread_one),
    path("notifications/<str:notification_id>/delete", views.delete_one),
    path("notifications/<str:notification_id>/delete/", views.delete_one),
    path("prefs", views.prefs),
    path("prefs/", views.prefs),
    path("telegram/link", views.telegram_link),
    path("telegram/link/", views.telegram_link),
    path("telegram/webhook", views.telegram_webhook),
    path("telegram/webhook/", views.telegram_webhook),
]
