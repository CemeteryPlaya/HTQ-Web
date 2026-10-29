"""Маршруты чек-листов (мастер-план канбана §6.3). Подключаются из
``urls.py``; ``APPEND_SLASH=False`` — каждое написание регистрируется явно,
пути — явными ``path(…, views.<имя>)`` для сторожа прав (``test_gate.py``)."""

from django.urls import path

from . import views_checklists as views

urlpatterns = [
    path("tasks/<int:task_id>/checklists", views.task_checklists),
    path("tasks/<int:task_id>/checklists/", views.task_checklists),
    path("checklists/<int:checklist_id>", views.checklist_detail),
    path("checklists/<int:checklist_id>/", views.checklist_detail),
    path("checklists/<int:checklist_id>/items", views.checklist_items),
    path("checklists/<int:checklist_id>/items/", views.checklist_items),
    path("checklist-items/<int:item_id>", views.checklist_item_detail),
    path("checklist-items/<int:item_id>/", views.checklist_item_detail),
]
