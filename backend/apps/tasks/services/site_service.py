"""Объекты (площадки) и их связь с проектами.

Новый домен — FastAPI-оригинала у него нет, поэтому здесь нет обычной для
этого аппа сноски «ported from ...».

Две вещи, которые стоит знать, прежде чем что-то менять:

* **Правило «объект задачи входит в объекты её проекта» живёт здесь, а не
  в БД.** Оно охватывает три таблицы (``tasks_task``, ``tasks_projectsite``),
  а ``CheckConstraint`` видит одну строку одной таблицы. Триггер мог бы, но
  в репозитории нет ни одного, и Django-миграции ими не управляют.
  ``Model.clean()`` тоже отпадает: он не вызывается из ``objects.create()``,
  а весь код пишет через сервисы — получился бы мёртвый код.
* **Пустой набор объектов у проекта разрешает любой объект.** Это правило,
  а не недосмотр: на момент выката ни у одного существующего проекта
  объектов нет, и строгая проверка сломала бы создание задач во всех них
  разом.
"""

from __future__ import annotations

from django.db import transaction
from django.http import Http404

from ..models import (Project, ProjectSite, Site, SiteBlock, SiteStatus, Task)


def list_sites(*, status: str | None = None,
               search: str | None = None) -> list[Site]:
    qs = Site.objects.all()
    if status:
        qs = qs.filter(status=status)
    if search:
        needle = search.strip()
        if needle:
            qs = qs.filter(name__icontains=needle)
    return list(qs.order_by("name"))


def get_site(site_id: int) -> Site:
    site = Site.objects.filter(pk=site_id).first()
    if site is None:
        raise Http404("Site not found")
    return site


def create_site(payload: dict) -> Site:
    return Site.objects.create(**payload)


def update_site(site_id: int, changes: dict) -> Site:
    site = get_site(site_id)
    for field, value in changes.items():
        setattr(site, field, value)
    site.save()
    return site


class SiteInUse(Exception):
    """Объект нельзя удалить: на него ссылаются задачи или проекты.

    Мягкая альтернатива есть и она правильная — статус ``closed``. Жёсткое
    удаление тут опаснее, чем кажется: ``Task.site`` это ``SET_NULL``, то
    есть удаление объекта, на который ссылаются только задачи, молча
    обнулило бы им объект и испортило отчётность задним числом.
    """

    def __init__(self, tasks: int, projects: int):
        self.tasks = tasks
        self.projects = projects
        super().__init__(
            f"Объект используется: задач — {tasks}, проектов — {projects}. "
            f"Переведите его в статус «закрыт» вместо удаления."
        )


def delete_site(site_id: int) -> None:
    site = get_site(site_id)
    tasks = Task.objects.filter(site_id=site_id, is_deleted=False).count()
    projects = ProjectSite.objects.filter(site_id=site_id).count()
    if tasks or projects:
        raise SiteInUse(tasks, projects)
    site.delete()


# ── связь проект ↔ объект ───────────────────────────────────────────────

def project_site_ids(project_id: int) -> list[int]:
    return list(ProjectSite.objects.filter(project_id=project_id)
                .values_list("site_id", flat=True))


def list_project_sites(project_id: int) -> list[ProjectSite]:
    return list(ProjectSite.objects.filter(project_id=project_id)
                .select_related("site")
                .order_by("-is_primary", "site__name"))


@transaction.atomic
def set_project_sites(project_id: int, site_ids: list[int],
                      primary_site_id: int | None = None) -> list[ProjectSite]:
    """Заменить набор объектов проекта целиком.

    Замена, а не добавление: форма проекта присылает полный список, и
    инкрементальный API заставил бы её вычислять разницу — ту самую
    арифметику, которую потом никто не проверяет. Существующие связи с
    датами не пересоздаются, чтобы не потерять период присутствия.
    """
    project = Project.objects.filter(pk=project_id).first()
    if project is None:
        raise Http404("Project not found")

    wanted = list(dict.fromkeys(site_ids))   # дедуп, порядок сохраняем
    known = set(Site.objects.filter(pk__in=wanted).values_list("id", flat=True))
    missing = [s for s in wanted if s not in known]
    if missing:
        raise ValueError(f"Объекты не найдены: {missing}")
    if primary_site_id is not None and primary_site_id not in known:
        raise ValueError(f"Основной объект не найден: {primary_site_id}")

    ProjectSite.objects.filter(project_id=project_id).exclude(
        site_id__in=wanted).delete()

    existing = {link.site_id: link
                for link in ProjectSite.objects.filter(project_id=project_id)}
    for site_id in wanted:
        is_primary = site_id == primary_site_id
        link = existing.get(site_id)
        if link is None:
            ProjectSite.objects.create(project_id=project_id, site_id=site_id,
                                       is_primary=is_primary)
        elif link.is_primary != is_primary:
            link.is_primary = is_primary
            link.save(update_fields=["is_primary", "updated_at"])

    return list_project_sites(project_id)


# ── валидация объекта задачи ────────────────────────────────────────────

def resolve_task_site(project_id: int | None,
                      site_id: int | None) -> int | None:
    """Проверить (и при возможности довыбрать) объект задачи.

    Правила, по порядку:

    * проект не задан → допустим любой существующий объект;
    * у проекта объектов нет → допустим любой (см. докстринг модуля);
    * объект не задан, а у проекта ровно один → наследуем его;
    * иначе объект обязан входить в ``ProjectSite`` проекта.

    Бросает ``ValueError`` — вызывающая вьюха переводит его в 400. Смена
    проекта на такой, где текущий объект не числится, при неприсланном
    ``site_id`` — тоже ошибка, а не молчаливое обнуление: тихая потеря
    данных отчётности хуже явного отказа.
    """
    if site_id is not None and not Site.objects.filter(pk=site_id).exists():
        raise ValueError(f"Объект {site_id} не найден")

    if project_id is None:
        return site_id

    allowed = project_site_ids(project_id)
    if not allowed:
        return site_id

    if site_id is None:
        return allowed[0] if len(allowed) == 1 else None

    if site_id not in allowed:
        raise ValueError(
            "Объект не относится к выбранному проекту. "
            "Выберите объект из списка объектов проекта."
        )
    return site_id


def resolve_task_block(site_id: int | None,
                       block_id: int | None) -> int | None:
    """Проверить (и при возможности довыбрать) блок задачи.

    Живёт рядом с ``resolve_task_site`` по той же причине: правило про две
    таблицы, ``CheckConstraint`` видит одну. Порядок правил тот же:

    * блок не задан → ничего не проверяем;
    * блок задан, а объекта у задачи нет → наследуем объект блока
      («развезти валы на блок 1» однозначно называет и площадку);
    * иначе блок обязан принадлежать объекту задачи.

    Возвращает ``block_id``; объект, который из него следует, вызывающий
    берёт через ``block_site_id`` — возвращать пару значило бы заставить
    все три места распаковывать кортеж ради редкого случая.
    """
    if block_id is None:
        return None

    owner = block_site_id(block_id)
    if owner is None:
        raise ValueError(f"Блок {block_id} не найден")
    if site_id is not None and owner != site_id:
        raise ValueError(
            "Блок не относится к объекту задачи. "
            "Выберите блок из списка блоков этого объекта."
        )
    return block_id


def block_site_id(block_id: int) -> int | None:
    return (SiteBlock.objects.filter(pk=block_id)
            .values_list("site_id", flat=True).first())


def build_response(site: Site) -> dict:
    return {
        "id": site.id,
        "name": site.name,
        "code": site.code,
        "description": site.description,
        "address": site.address,
        "region": site.region,
        "latitude": float(site.latitude) if site.latitude is not None else None,
        "longitude": float(site.longitude) if site.longitude is not None else None,
        "status": str(site.status),
        "color": site.color,
        "department_id": site.department_id,
        "manager_id": site.manager_id,
        "created_at": str(site.created_at),
        "updated_at": str(site.updated_at),
    }


def build_responses(sites: list[Site]) -> list[dict]:
    return [build_response(s) for s in sites]


def build_project_site_ref(link: ProjectSite) -> dict:
    return {
        "id": link.site_id,
        "name": link.site.name,
        "color": link.site.color,
        "status": str(link.site.status),
        "is_primary": link.is_primary,
        "start_date": str(link.start_date) if link.start_date else None,
        "end_date": str(link.end_date) if link.end_date else None,
    }


__all__ = [
    "SiteInUse", "SiteStatus",
    "list_sites", "get_site", "create_site", "update_site", "delete_site",
    "project_site_ids", "list_project_sites", "set_project_sites",
    "resolve_task_site", "resolve_task_block", "block_site_id",
    "build_response", "build_responses", "build_project_site_ref",
]
