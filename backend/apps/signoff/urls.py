"""Маршруты ``/api/signoff/v1/*``.

Монтируются автоматически по ``SignoffConfig.API_PREFIX`` — ``htqweb/urls.py``
не правится (правило №3, backend/README.md).

``APPEND_SLASH = False``: Django сам не редиректит ``/foo`` → ``/foo/``, и
такой редирект на части клиентов теряет заголовок ``Authorization``. Поэтому
каждый путь зарегистрирован в обоих написаниях — со слэшем и без.
"""

from django.urls import path

from . import views

urlpatterns = [
    # ── Служебное ──
    path("enums", views.EnumsView.as_view()),
    path("enums/", views.EnumsView.as_view()),
    path("subjects", views.SubjectsView.as_view()),
    path("subjects/", views.SubjectsView.as_view()),

    # ── Маршруты ──
    # Вложенный `stages` регистрируется РАНЬШЕ `<int:route_id>`: Django
    # перебирает шаблоны сверху вниз, и хотя эти два не пересекаются (разное
    # число сегментов), более специфичный путь выше — порядок, который не
    # сломается при добавлении соседних вложенных маршрутов.
    path("routes/<int:route_id>/stages", views.RouteStagesView.as_view()),
    path("routes/<int:route_id>/stages/", views.RouteStagesView.as_view()),
    path("routes", views.RouteCollectionView.as_view()),
    path("routes/", views.RouteCollectionView.as_view()),
    path("routes/<int:route_id>", views.RouteDetailView.as_view()),
    path("routes/<int:route_id>/", views.RouteDetailView.as_view()),

    # ── Этапы маршрута ──
    path("stages/<int:stage_id>", views.StageDetailView.as_view()),
    path("stages/<int:stage_id>/", views.StageDetailView.as_view()),

    # ── Процессы ──
    path("processes/<int:process_id>/cancel", views.ProcessCancelView.as_view()),
    path("processes/<int:process_id>/cancel/", views.ProcessCancelView.as_view()),
    path("processes/<int:process_id>/rework", views.ProcessReworkView.as_view()),
    path("processes/<int:process_id>/rework/", views.ProcessReworkView.as_view()),
    path("processes", views.ProcessCollectionView.as_view()),
    path("processes/", views.ProcessCollectionView.as_view()),
    path("processes/<int:process_id>", views.ProcessDetailView.as_view()),
    path("processes/<int:process_id>/", views.ProcessDetailView.as_view()),

    # ── Решения ──
    # "mine" — до любого `<int:task_id>`, иначе строка ушла бы в int-конвертер
    # и дала 404 вместо маршрута.
    path("tasks/mine", views.InboxView.as_view()),
    path("tasks/mine/", views.InboxView.as_view()),
    path("tasks/<int:task_id>/decision", views.TaskDecisionView.as_view()),
    path("tasks/<int:task_id>/decision/", views.TaskDecisionView.as_view()),
    # Документ прикладывается ДО решения, отдельным запросом — см. докстринг
    # services/attachments.py.
    path("tasks/<int:task_id>/attachment", views.TaskAttachmentView.as_view()),
    path("tasks/<int:task_id>/attachment/", views.TaskAttachmentView.as_view()),
]
