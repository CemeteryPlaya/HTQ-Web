"""Субподрядчики: организации, их представители и привлечения.

Новый домен — FastAPI-оригинала нет.

**Что «только справочник, без входа» значит буквально на этом этапе.**
``ContractorWorker.user_id`` не заполняет ничто, ``apps.users`` не получает
ни строки кода, ``task_service.scope_for``/``visibility_q`` подрядчиков не
читают, ``profile_service.roles_for`` не меняется. Уровни (junior / middle /
senior) уже хранятся и уже показываются в интерфейсе, но правами пока не
управляют — это следующая итерация, и она не потребует миграций, потому что
все нужные колонки заведены здесь.

Единица привлечения — пара «организация + объект»: именно в ней
сформулировано право senior «видеть все задачи своей организации по
объекту», так что скоуп видимости вырастет отсюда без изменения схемы.
"""

from __future__ import annotations

from django.db.models import Q
from django.http import Http404

from ..models import (
    Contractor,
    ContractorEngagement,
    ContractorWorker,
    Equipment,
    Task,
)


class ContractorInUse(Exception):
    """Организацию нельзя удалить: на неё ссылаются задачи, техника, люди
    или привлечения.

    Правильный жест здесь — статус ``archived``, а не удаление: ``Task.
    contractor`` это ``SET_NULL``, и удаление молча стёрло бы атрибуцию
    выполненных работ задним числом.
    """

    def __init__(self, tasks: int, equipment: int, workers: int,
                 engagements: int):
        super().__init__(
            f"Подрядчик используется: задач — {tasks}, техники — {equipment}, "
            f"людей — {workers}, привлечений — {engagements}. "
            f"Переведите его в архив вместо удаления."
        )


# ── организации ─────────────────────────────────────────────────────────

def list_contractors(*, status: str | None = None,
                     search: str | None = None) -> list[Contractor]:
    qs = Contractor.objects.all()
    if status:
        qs = qs.filter(status=status)
    if search and search.strip():
        needle = search.strip()
        qs = qs.filter(name__icontains=needle)
    return list(qs.order_by("name"))


def get_contractor(contractor_id: int) -> Contractor:
    row = Contractor.objects.filter(pk=contractor_id).first()
    if row is None:
        raise Http404("Contractor not found")
    return row


def create_contractor(payload: dict) -> Contractor:
    return Contractor.objects.create(**payload)


def update_contractor(contractor_id: int, changes: dict) -> Contractor:
    row = get_contractor(contractor_id)
    for field, value in changes.items():
        setattr(row, field, value)
    row.save()
    return row


def delete_contractor(contractor_id: int) -> None:
    row = get_contractor(contractor_id)
    counts = (
        Task.objects.filter(contractor_id=contractor_id,
                            is_deleted=False).count(),
        Equipment.objects.filter(contractor_id=contractor_id).count(),
        ContractorWorker.objects.filter(contractor_id=contractor_id).count(),
        ContractorEngagement.objects.filter(
            contractor_id=contractor_id).count(),
    )
    if any(counts):
        raise ContractorInUse(*counts)
    row.delete()


# ── представители ───────────────────────────────────────────────────────

def list_workers(*, contractor_id: int | None = None,
                 active_only: bool = True) -> list[ContractorWorker]:
    qs = ContractorWorker.objects.select_related("contractor")
    if contractor_id is not None:
        qs = qs.filter(contractor_id=contractor_id)
    if active_only:
        qs = qs.filter(is_active=True)
    return list(qs.order_by("last_name", "first_name"))


def get_worker(worker_id: int) -> ContractorWorker:
    row = (ContractorWorker.objects.select_related("contractor")
           .filter(pk=worker_id).first())
    if row is None:
        raise Http404("Contractor worker not found")
    return row


def create_worker(contractor_id: int, payload: dict) -> ContractorWorker:
    get_contractor(contractor_id)      # 404 раньше, чем IntegrityError
    return ContractorWorker.objects.create(contractor_id=contractor_id,
                                           **payload)


def update_worker(worker_id: int, changes: dict) -> ContractorWorker:
    row = get_worker(worker_id)
    for field, value in changes.items():
        setattr(row, field, value)
    row.save()
    return row


def delete_worker(worker_id: int) -> None:
    """Мягкое отключение: исторические задачи ссылаются на человека, и
    жёсткое удаление обнулило бы им исполнителя (``SET_NULL``)."""
    row = get_worker(worker_id)
    row.is_active = False
    row.save(update_fields=["is_active", "updated_at"])


# ── привлечения ─────────────────────────────────────────────────────────

def list_engagements(*, contractor_id: int | None = None,
                     project_id: int | None = None,
                     site_id: int | None = None,
                     roadmap_id: int | None = None,
                     active_only: bool = False) -> list[ContractorEngagement]:
    qs = ContractorEngagement.objects.select_related(
        "contractor", "project", "site", "roadmap")
    if contractor_id is not None:
        qs = qs.filter(contractor_id=contractor_id)
    if project_id is not None:
        qs = qs.filter(project_id=project_id)
    if site_id is not None:
        qs = qs.filter(site_id=site_id)
    if roadmap_id is not None:
        qs = qs.filter(roadmap_id=roadmap_id)
    if active_only:
        qs = qs.filter(is_active=True)
    return list(qs.order_by("-is_active", "contractor__name", "-start_date"))


def get_engagement(engagement_id: int) -> ContractorEngagement:
    row = (ContractorEngagement.objects
           .select_related("contractor", "project", "site", "roadmap")
           .filter(pk=engagement_id).first())
    if row is None:
        raise Http404("Engagement not found")
    return row


def create_engagement(payload: dict) -> ContractorEngagement:
    get_contractor(payload["contractor_id"])
    if not (payload.get("project_id") or payload.get("site_id")
            or payload.get("roadmap_id")):
        # Дублирует CHECK в БД сознательно: сообщение здесь человеческое, а
        # IntegrityError дал бы 500 вместо 400.
        raise ValueError("Укажите проект, объект или роудмап (хотя бы одно)")
    return ContractorEngagement.objects.create(**payload)


def update_engagement(engagement_id: int, changes: dict) -> ContractorEngagement:
    row = get_engagement(engagement_id)
    for field, value in changes.items():
        setattr(row, field, value)
    if row.project_id is None and row.site_id is None and row.roadmap_id is None:
        raise ValueError("Укажите проект, объект или роудмап (хотя бы одно)")
    row.save()
    return row


def delete_engagement(engagement_id: int) -> None:
    get_engagement(engagement_id).delete()


# ── наследование подрядчика вниз по иерархии ────────────────────────────

def effective_contractors(tasks) -> dict[int, dict | None]:
    """Кто фактически выполняет каждую задачу: своё значение или унаследованное.

    Порядок от частного к общему: собственный ``Task.contractor`` →
    привлечение на роудмап → на площадку → на проект. Первое найденное
    выигрывает; ничего не найдено — «своя команда» (``None``).

    Зачем вообще: подрядчика назначают на пакет работ или на площадку
    целиком, а не задача за задачей. Без разрешения «кто здесь работает»
    приходилось выяснять глазами, поднимаясь по дереву руками.

    Почему по ``ContractorEngagement``, а не по FK на каждом уровне (как
    предлагает SPEC §3.1): привлечение УЖЕ ключуется на проект, площадку и
    роудмап и вдобавок несёт договор и сроки. Дублировать его тремя
    отдельными колонками значило бы завести второй способ сказать то же
    самое и получить два расходящихся ответа.

    Батчем, а не по задаче: карта строится двумя запросами на весь список
    (конвенция ``hydration``/``_metrics_batch``). Возвращает
    ``{task_id: {"id", "name"} | None}``.
    """
    tasks = list(tasks)
    if not tasks:
        return {}

    # Собственные подрядчики задач — уже в объектах (select_related), но
    # имя нужно и для унаследованных, поэтому справочник собираем один.
    roadmap_ids = {t.roadmap_id for t in tasks if t.roadmap_id}
    site_ids = {t.site_id for t in tasks if t.site_id}
    project_ids = {t.project_id for t in tasks if t.project_id}

    by_roadmap: dict[int, tuple[int, str]] = {}
    by_site: dict[int, tuple[int, str]] = {}
    by_project: dict[int, tuple[int, str]] = {}
    if roadmap_ids or site_ids or project_ids:
        rows = (ContractorEngagement.objects
                .filter(is_active=True)
                .filter(Q(roadmap_id__in=roadmap_ids)
                        | Q(site_id__in=site_ids)
                        | Q(project_id__in=project_ids))
                .select_related("contractor")
                # Свежие привлечения важнее: если на площадку заводили
                # подряд два договора, действует последний.
                .order_by("start_date", "id"))
        for row in rows:
            pair = (row.contractor_id, row.contractor.name)
            # Строка привлечения может называть сразу несколько целей
            # (проект + площадка) — раскладываем во все подходящие карты,
            # приоритет между ними разбирается ниже, при выборе.
            if row.roadmap_id in roadmap_ids:
                by_roadmap[row.roadmap_id] = pair
            if row.site_id in site_ids:
                by_site[row.site_id] = pair
            if row.project_id in project_ids:
                by_project[row.project_id] = pair

    out: dict[int, dict | None] = {}
    for task in tasks:
        if task.contractor_id:
            found = (task.contractor_id, task.contractor.name)
        else:
            found = (by_roadmap.get(task.roadmap_id)
                     or by_site.get(task.site_id)
                     or by_project.get(task.project_id))
        out[task.id] = ({"id": found[0], "name": found[1]} if found else None)
    return out


def engagement_site_ids(contractor_id: int) -> list[int]:
    """Объекты, на которые подрядчик привлечён.

    Пока не используется в авторизации — это вход для будущей ветки
    ``_contractor_visibility_q``: она сузит видимость до задач своей
    организации на этих объектах.
    """
    return list(
        ContractorEngagement.objects
        .filter(contractor_id=contractor_id, is_active=True,
                site_id__isnull=False)
        .values_list("site_id", flat=True)
    )


# ── ответы ──────────────────────────────────────────────────────────────

def build_contractor(row: Contractor) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "short_name": row.short_name,
        "bin_iin": row.bin_iin,
        "contact_person": row.contact_person,
        "phone": row.phone,
        "email": row.email,
        "address": row.address,
        "notes": row.notes,
        "status": str(row.status),
        "created_at": str(row.created_at),
        "updated_at": str(row.updated_at),
    }


def build_worker(row: ContractorWorker) -> dict:
    return {
        "id": row.id,
        "contractor_id": row.contractor_id,
        "contractor_name": row.contractor.name,
        "last_name": row.last_name,
        "first_name": row.first_name,
        "middle_name": row.middle_name,
        "full_name": row.full_name,
        "phone": row.phone,
        "email": row.email,
        "position_title": row.position_title,
        "level": str(row.level),
        "user_id": row.user_id,
        "is_active": row.is_active,
        "created_at": str(row.created_at),
        "updated_at": str(row.updated_at),
    }


def build_engagement(row: ContractorEngagement) -> dict:
    return {
        "id": row.id,
        "contractor_id": row.contractor_id,
        "contractor_name": row.contractor.name,
        "project_id": row.project_id,
        "project_name": row.project.name if row.project else None,
        "site_id": row.site_id,
        "site_name": row.site.name if row.site else None,
        "roadmap_id": row.roadmap_id,
        "roadmap_name": row.roadmap.name if row.roadmap else None,
        "contract_no": row.contract_no,
        "scope": row.scope,
        "start_date": str(row.start_date) if row.start_date else None,
        "end_date": str(row.end_date) if row.end_date else None,
        "is_active": row.is_active,
        "created_at": str(row.created_at),
        "updated_at": str(row.updated_at),
    }


__all__ = [
    "ContractorInUse",
    "list_contractors", "get_contractor", "create_contractor",
    "update_contractor", "delete_contractor",
    "list_workers", "get_worker", "create_worker", "update_worker",
    "delete_worker",
    "list_engagements", "get_engagement", "create_engagement",
    "update_engagement", "delete_engagement", "engagement_site_ids",
    "effective_contractors",
    "build_contractor", "build_worker", "build_engagement",
]
