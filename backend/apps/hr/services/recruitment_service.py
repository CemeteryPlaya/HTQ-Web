"""Бизнес-логика рекрутинга (вакансии + отклики) — порт
services/hr/app/services/recruitment_service.py (+ repositories/vacancy_repo.py,
repositories/base_repo.py в части, которую он использовал).

Решения, зафиксированные при переносе (docs/plans/2026-07-20-hr-domain.md,
под-модуль hr-recruiting):

* Авторизация — БУКВАЛЬНО как в исходнике: ``vacancies.py``/``applications.py``
  роутеров исходника используют ТОЛЬКО ``get_current_user`` — ни один
  эндпойнт (включая POST/PUT/DELETE) не зовёт ``require_hr_write``, в
  отличие от positions/org, где записи защищены ``is_elevated``. Это
  странность исходника, не баг порта: все 13 эндпойнтов здесь —
  ``api_view(auth="jwt")`` без ``admin=True``, и ``apps.hr.access``
  (HRAccess/resolve_hr_access) тоже не задействован — recruiting в
  исходнике не использует и его.
* ``archive()`` (GET /applications/archive/) в исходнике джойнит модель
  ``Document`` (``app/models/document.py``). Document ещё НЕ перенесена в
  apps.hr (под-модуль hr-docs, задача 5 плана, ещё не исполнена — растяжка
  ``test_documents_endpoint_todo_is_tracked`` в test_employees_api.py прямо
  запрещает вводить модель Document раньше времени). Поэтому здесь
  ``documents`` — ВСЕГДА пустой список; когда hr-docs перенесётся, дописать
  реальный запрос и снять эту деградацию.
* ``closed_statuses`` для archive включает "withdrawn"/"archived" — значения,
  которых НЕТ в ``ApplicationStatusLiteral`` (ни один эндпойнт не может
  реально выставить такой статус через API). Мёртвая ветка фильтра исходника
  — переносится как есть (контракт, не баг), а не сокращается до
  реально достижимых статусов.
* ``change_status`` пишет ``notes`` в патч только если оно truthy
  (``if data.notes:``), а не ``is not None`` — пустая строка НЕ
  перезаписывает существующие notes. Буквальный порт этой особенности.
* Никаких @transaction.atomic-обёрток сверх стандартного autocommit-запроса:
  каждая мутация здесь — одна строка (в отличие от positions, где
  многошаговый ребаланс требует явной атомарности).
"""
from __future__ import annotations

from datetime import date

from apps.hr.models import Application, Vacancy

_ARCHIVE_STATUSES = {"rejected", "hired", "withdrawn", "archived"}


class VacancyNotFound(Exception):
    """404: вакансия не найдена."""


class ApplicationNotFound(Exception):
    """404: отклик не найден."""


# ── сериализаторы (формы из schemas/vacancy.py, schemas/application.py) ─────

def serialize_vacancy(v: Vacancy) -> dict:
    """VacancyOut."""
    return {
        "id": v.id,
        "title": v.title,
        "department_id": v.department_id,
        "position_id": v.position_id,
        "description": v.description,
        "requirements": v.requirements,
        "status": v.status,
        "assigned_recruiter_id": v.assigned_recruiter_id,
        "opened_at": v.opened_at.isoformat(),
        "closed_at": v.closed_at.isoformat() if v.closed_at else None,
        "created_at": v.created_at.isoformat(),
        "updated_at": v.updated_at.isoformat(),
    }


def serialize_application(a: Application) -> dict:
    """ApplicationOut."""
    return {
        "id": a.id,
        "vacancy_id": a.vacancy_id,
        "candidate_name": a.candidate_name,
        "candidate_email": a.candidate_email,
        "candidate_phone": a.candidate_phone,
        "resume_url": a.resume_url,
        "cover_letter": a.cover_letter,
        "notes": a.notes,
        "status": a.status,
        "applied_at": a.applied_at.isoformat(),
        "created_at": a.created_at.isoformat(),
        "updated_at": a.updated_at.isoformat(),
    }


def paginate(items: list[dict], *, total: int, page: int, limit: int) -> dict:
    """PaginatedResponse envelope — форма ТОЧНО как schemas/common.py."""
    pages = (total + limit - 1) // limit
    return {"items": items, "total": total, "page": page, "pages": pages, "limit": limit}


# ── вакансии ─────────────────────────────────────────────────────────────

def list_vacancies(
    *, status: str | None = None, department_id: int | None = None, page: int = 1, limit: int = 20,
) -> tuple[list[Vacancy], int]:
    qs = Vacancy.objects.all()
    if status:
        qs = qs.filter(status=status)
    if department_id:
        qs = qs.filter(department_id=department_id)
    qs = qs.order_by("-created_at")
    total = qs.count()
    offset = (page - 1) * limit
    items = list(qs[offset:offset + limit])
    return items, total


def get_vacancy(id: int) -> Vacancy:
    vacancy = Vacancy.objects.filter(id=id).first()
    if vacancy is None:
        raise VacancyNotFound
    return vacancy


def create_vacancy(data) -> Vacancy:
    return Vacancy.objects.create(**data.model_dump())


def update_vacancy(id: int, data) -> Vacancy:
    vacancy = get_vacancy(id)
    patch = data.model_dump(exclude_none=True)
    for field, value in patch.items():
        setattr(vacancy, field, value)
    if patch:
        vacancy.save()
    return vacancy


def close_vacancy(id: int) -> None:
    vacancy = get_vacancy(id)
    vacancy.status = "closed"
    vacancy.closed_at = date.today()
    vacancy.save()


def get_vacancy_applications(vacancy_id: int) -> list[Application]:
    get_vacancy(vacancy_id)  # 404 если вакансии нет
    return list(Application.objects.filter(vacancy_id=vacancy_id).order_by("-applied_at"))


# ── отклики ──────────────────────────────────────────────────────────────

def list_applications(*, page: int = 1, limit: int = 20) -> tuple[list[Application], int]:
    qs = Application.objects.order_by("-applied_at")
    total = qs.count()
    offset = (page - 1) * limit
    items = list(qs[offset:offset + limit])
    return items, total


def get_application(id: int) -> Application:
    app = Application.objects.filter(id=id).first()
    if app is None:
        raise ApplicationNotFound
    return app


def create_application(data) -> Application:
    get_vacancy(data.vacancy_id)  # 404 "Vacancy not found", НЕ 422, если промах
    return Application.objects.create(**data.model_dump())


def update_application(id: int, data) -> Application:
    app = get_application(id)
    patch = data.model_dump(exclude_none=True)
    for field, value in patch.items():
        setattr(app, field, value)
    if patch:
        app.save()
    return app


def change_status(id: int, data) -> Application:
    app = get_application(id)
    app.status = data.status
    # Буквальный порт: ``if data.notes:`` (truthy), не ``is not None`` —
    # пустая строка не затирает существующие notes.
    if data.notes:
        app.notes = data.notes
    app.save()
    return app


def delete_application(id: int) -> None:
    app = get_application(id)
    app.delete()


def archive() -> dict:
    """Порт ``GET /applications/archive/`` — HRArchiveResponse.

    ``documents`` всегда пустой список — см. докстринг модуля (Document
    ещё не перенесена в apps.hr).
    """
    apps_qs = Application.objects.filter(status__in=_ARCHIVE_STATUSES).order_by("-created_at")
    return {
        "applications": [
            {
                "id": a.id,
                "vacancy_id": a.vacancy_id,
                "candidate_name": a.candidate_name,
                "candidate_email": a.candidate_email,
                "status": a.status,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in apps_qs
        ],
        "documents": [],
    }
