"""Маршруты /api/conference/v1/ (монтируются по AppConfig.API_PREFIX).

Каждый путь зарегистрирован в двух написаниях — со слешем и без. Это не
избыточность: ``APPEND_SLASH = False``, поэтому Django сам редирект не
поставит, а 307 на редиректе теряет заголовок Authorization в части
браузеров. Та же конвенция во всех аппках платформы (см. apps/cms/urls.py).
"""

from django.urls import path

from . import views

urlpatterns = [
    # ── Внутренний канал SFU → Django. Регистрируется ПЕРВЫМ, чтобы
    # `internal` не был перехвачен ничем другим, и живёт под общим префиксом
    # /api/conference/v1/ намеренно: так ServiceGateMiddleware гасит приём
    # фактов тем же флагом сервиса, что и чтение истории.
    path("internal/sessions", views.internal_session_start),
    path("internal/sessions/", views.internal_session_start),
    path("internal/sessions/<int:session_id>/participants",
         views.internal_participant),
    path("internal/sessions/<int:session_id>/participants/",
         views.internal_participant),
    path("internal/sessions/<int:session_id>/events", views.internal_event),
    path("internal/sessions/<int:session_id>/events/", views.internal_event),
    path("internal/sessions/<int:session_id>/artifacts", views.internal_artifacts),
    path("internal/sessions/<int:session_id>/artifacts/", views.internal_artifacts),
    path("internal/sessions/<int:session_id>/finish", views.internal_session_finish),
    path("internal/sessions/<int:session_id>/finish/", views.internal_session_finish),

    # ── Публичное чтение истории.
    path("sessions", views.sessions),
    path("sessions/", views.sessions),
    path("sessions/<int:session_id>/transcript", views.session_transcript),
    path("sessions/<int:session_id>/transcript/", views.session_transcript),
    path("sessions/<int:session_id>/recording", views.session_recording),
    path("sessions/<int:session_id>/recording/", views.session_recording),
    path("sessions/<int:session_id>/poster", views.session_poster),
    path("sessions/<int:session_id>/poster/", views.session_poster),
    path("sessions/<int:session_id>/events", views.session_events),
    path("sessions/<int:session_id>/events/", views.session_events),
    path("sessions/<int:session_id>", views.session_detail),
    path("sessions/<int:session_id>/", views.session_detail),
]
