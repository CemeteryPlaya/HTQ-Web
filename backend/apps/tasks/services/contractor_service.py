"""Партнёры: организации, их представители и привлечения.

Новый домен — FastAPI-оригинала нет.

**Что «только справочник, без входа» значит буквально на этом этапе.**
``ContractorWorker.user_id`` не заполняет ничто, ``apps.users`` не получает
ни строки кода, ``task_service.scope_for``/``visibility_q`` партнёров не
читают, ``profile_service.roles_for`` не меняется. Уровни (junior / middle /
senior) уже хранятся и уже показываются в интерфейсе, но правами пока не
управляют — это следующая итерация, и она не потребует миграций, потому что
все нужные колонки заведены здесь.

Единица привлечения — пара «организация + объект»: именно в ней
сформулировано право senior «видеть все задачи своей организации по
объекту», так что скоуп видимости вырастет отсюда без изменения схемы.

**Связь с «Договорами».** Партнёр — это контрагент (``contracts.
Counterparty``) в роли исполнителя на объектах, привлечение — работа по
договору (``contracts.Agreement``). Обе ссылки — голые id (междоменный FK
запрещён), поэтому целостность держится здесь, через
``apps.contracts.interface``: контрагент существует, БИН/ИИН у пары один,
договор привлечения заключён с контрагентом ЭТОГО партнёра. На записи
выключенные «Договоры» — честный 503 (``ServiceDisabled`` не глушится: он
решает, допустима ли связь), на чтении — карточка без реквизитов
контрагента, а не упавший список партнёров.
"""

from __future__ import annotations

import re

from django.db import transaction
from django.db.models import Q

from apps.contracts import interface as contracts
from apps.core.services import ServiceDisabled
from htqweb import date_rules
from htqweb.fallback import fallback
from django.http import Http404

from ..models import (
    Contractor,
    ContractorEngagement,
    ContractorWorker,
    Equipment,
    Task,
)

# Форма БИН/ИИН, которую принимает партнёр (``schemas.ContractorCreate``).
# У контрагента поле шире — иностранный номер другой формы, — и такой номер
# партнёру не переносится: ему некуда лечь.
_KZ_BIN = re.compile(r"\d{12}")


class CounterpartyLinkConflict(Exception):
    """Связь с «Договорами» противоречит данным: контрагент уже у другого
    партнёра, БИН/ИИН пары расходится, договор заключён с другим
    контрагентом. Вьюха отдаёт 409 с этим текстом."""


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
            f"Партнёр используется: задач — {tasks}, техники — {equipment}, "
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
    row = Contractor(**payload)
    _check_counterparty_link(row)
    row.save(force_insert=True)
    return row


def update_contractor(contractor_id: int, changes: dict) -> Contractor:
    row = get_contractor(contractor_id)
    previous_counterparty = row.counterparty_id
    changed = _changed_fields(row, changes)
    for field, value in changes.items():
        setattr(row, field, value)
    # БИН сверяется и при его собственной правке: иначе связанному партнёру
    # можно было бы вписать чужой номер, и пара разошлась бы после связывания.
    if {"counterparty_id", "bin_iin"} & changed:
        _check_counterparty_link(row)
    with transaction.atomic():
        row.save()
        if row.counterparty_id != previous_counterparty:
            # Договор привлечения — договор С КОНТРАГЕНТОМ этого партнёра.
            # Сменился контрагент — старые ссылки больше не про него. Номер
            # в ``contract_no`` остаётся: история привлечения не теряется.
            ContractorEngagement.objects.filter(
                contractor=row, agreement_id__isnull=False,
            ).update(agreement_id=None)
    return row


def _changed_fields(row, changes: dict) -> set[str]:
    """Поля, которые PATCH действительно меняет.

    Форма шлёт карточку целиком, и реагировать на «поле пришло» значило бы
    ходить в «Договоры» при каждой правке телефона — а при выключенном
    модуле отвечать на неё 503, хотя связи правка не касается.
    """
    return {field for field, value in changes.items()
            if getattr(row, field) != value}


def link_counterparty(contractor_id: int, counterparty_id: int) -> Contractor:
    """Связать партнёра с контрагентом — вход со стороны «Договоров»
    (карточка контрагента, заведённая «из партнёра»).

    В отличие от правки карточки партнёра, молча ПЕРЕвязать нельзя: из
    «Договоров» не видно, что партнёр уже числится за другим контрагентом,
    и перепривязка отняла бы его у того без следа.
    """
    row = get_contractor(contractor_id)
    if row.counterparty_id not in (None, counterparty_id):
        raise CounterpartyLinkConflict(
            f"Партнёр «{row.name}» уже связан с другим контрагентом")
    return update_contractor(contractor_id, {"counterparty_id": counterparty_id})


def unlink_counterparty(counterparty_id: int) -> None:
    """Контрагента удалили в «Договорах» — у партнёра не должно остаться
    ссылки в пустоту. Договоров у удалённого контрагента быть не могло
    (``PROTECT``), так что привлечения не трогаем."""
    Contractor.objects.filter(counterparty_id=counterparty_id).update(
        counterparty_id=None)


def _check_counterparty_link(row: Contractor) -> None:
    """Проверить связь с контрагентом и довести пару до согласованного вида.

    БИН/ИИН — идентичность организации, поэтому у связанной пары он один:
    разные номера — конфликт, а не «чей-то правее». Пустой БИН партнёра
    заполняется номером контрагента (если тот казахстанской формы).
    Остальные реквизиты НЕ навязываются: их подтягивает форма по кнопке, а
    дальше партнёр ведёт свои контакты сам — прораб на объекте не обязан
    совпадать с генеральным директором из договорной карточки.
    """
    if row.counterparty_id is None:
        return
    found = contracts.get_counterparties_brief([row.counterparty_id])
    if not found:
        raise Http404("Контрагент не найден в модуле «Договоры»")
    counterparty = found[0]

    taken = (Contractor.objects.filter(counterparty_id=row.counterparty_id)
             .exclude(pk=row.pk).first())
    if taken is not None:
        raise CounterpartyLinkConflict(
            f"Контрагент «{counterparty['name']}» уже связан с партнёром "
            f"«{taken.name}»")

    cp_bin = (counterparty["bin_iin"] or "").strip()
    if row.bin_iin:
        if row.bin_iin != cp_bin:
            raise CounterpartyLinkConflict(
                f"БИН/ИИН партнёра ({row.bin_iin}) не совпадает с БИН/ИИН "
                f"контрагента «{counterparty['name']}» ({cp_bin})")
    elif _KZ_BIN.fullmatch(cp_bin):
        clash = (Contractor.objects.filter(bin_iin=cp_bin)
                 .exclude(pk=row.pk).first())
        if clash is not None:
            raise CounterpartyLinkConflict(
                f"БИН/ИИН {cp_bin} уже указан у партнёра «{clash.name}»")
        row.bin_iin = cp_bin


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
    contractor = get_contractor(payload["contractor_id"])
    if not (payload.get("project_id") or payload.get("site_id")
            or payload.get("roadmap_id")):
        # Дублирует CHECK в БД сознательно: сообщение здесь человеческое, а
        # IntegrityError дал бы 500 вместо 400.
        raise ValueError("Укажите проект, объект или роудмап (хотя бы одно)")
    row = ContractorEngagement(**payload)
    row.contractor = contractor
    _check_agreement_link(row)
    row.save(force_insert=True)
    return row


def update_engagement(engagement_id: int, changes: dict) -> ContractorEngagement:
    row = get_engagement(engagement_id)
    changed = _changed_fields(row, changes)
    for field, value in changes.items():
        setattr(row, field, value)
    if row.project_id is None and row.site_id is None and row.roadmap_id is None:
        raise ValueError("Укажите проект, объект или роудмап (хотя бы одно)")
    # По СЛИТОЙ паре, а не по присланным полям: в PATCH может приехать
    # одна дата, вторая лежит в строке. Без этой проверки нарушение
    # доходит до CheckConstraint и возвращается как 500.
    date_rules.assert_instance_ordered(row)
    # И при правке одного ``contract_no``: у привязанного договора номер —
    # его, иначе в списке показывался бы один номер, а ссылка вела на другой.
    if {"agreement_id", "contract_no"} & changed:
        _check_agreement_link(row)
    row.save()
    return row


def _check_agreement_link(row: ContractorEngagement) -> None:
    """Договор привлечения — договор с контрагентом ЭТОГО партнёра.

    Номер договора ложится в ``contract_no``: так он виден в списках без
    похода в «Договоры» и переживает выключение модуля. Снятие ссылки
    (``agreement_id=None``) номер не стирает — это история привлечения.
    """
    if row.agreement_id is None:
        return
    counterparty_id = row.contractor.counterparty_id
    if counterparty_id is None:
        raise CounterpartyLinkConflict(
            f"Партнёр «{row.contractor.name}» не связан с контрагентом из "
            f"«Договоров» — сначала укажите контрагента в карточке партнёра")
    found = contracts.get_agreements_brief([row.agreement_id])
    if not found:
        raise Http404("Договор не найден в модуле «Договоры»")
    agreement = found[0]
    if agreement["counterparty_id"] != counterparty_id:
        raise CounterpartyLinkConflict(
            f"Договор {agreement['number']} заключён с другим контрагентом, "
            f"не с «{row.contractor.name}»")
    row.contract_no = agreement["number"]


def delete_engagement(engagement_id: int) -> None:
    get_engagement(engagement_id).delete()


# ── наследование партнёра вниз по иерархии ────────────────────────────

def effective_contractors(tasks) -> dict[int, dict | None]:
    """Кто фактически выполняет каждую задачу: своё значение или унаследованное.

    Порядок от частного к общему: собственный ``Task.contractor`` →
    привлечение на роудмап → на площадку → на проект. Первое найденное
    выигрывает; ничего не найдено — «своя команда» (``None``).

    Зачем вообще: партнёра назначают на пакет работ или на площадку
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

    # Собственные партнёры задач — уже в объектах (select_related), но
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
    """Объекты, на которые партнёр привлечён.

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

def _contracts_briefs(fetch, ids: set[int], *, site: str, what: str) -> dict[int, dict]:
    """Реквизиты из «Договоров» для подписи в ответе — батчем, с деградацией.

    Выключенный модуль стоит подписи, а не ответа: список партнёров нужен
    и компании без «Договоров». Это предусмотренная деградация
    (``expected=True``), а не сбой — такая компания штатно живёт без модуля.
    Проверки на записи (``_check_*``) ``ServiceDisabled`` НЕ глушат.
    """
    if not ids:
        return {}
    try:
        return {brief["id"]: brief for brief in fetch(ids)}
    except ServiceDisabled as exc:
        return fallback(site, {}, reason=f"модуль «Договоры» выключен — {what}",
                        expected=True, exc=exc)


def _counterparty_ref(brief: dict | None) -> dict | None:
    if brief is None:
        return None
    return {key: brief[key] for key in
            ("id", "name", "bin_iin", "status", "approval_state")}


def build_contractors(rows) -> list[dict]:
    """Карточки партнёров одним проходом: контрагенты — одним вызовом
    ``contracts.get_counterparties_brief`` на весь список, а не по строке."""
    rows = list(rows)
    counterparties = _contracts_briefs(
        contracts.get_counterparties_brief,
        {row.counterparty_id for row in rows if row.counterparty_id},
        site="tasks.contractors.counterparty_brief",
        what="партнёры без реквизитов контрагента")
    return [
        {
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
            "counterparty_id": row.counterparty_id,
            # ``None`` при заполненном ``counterparty_id`` — «Договоры»
            # выключены: связь есть, показать её нечем.
            "counterparty": _counterparty_ref(
                counterparties.get(row.counterparty_id)),
            "created_at": str(row.created_at),
            "updated_at": str(row.updated_at),
        }
        for row in rows
    ]


def build_contractor(row: Contractor) -> dict:
    return build_contractors([row])[0]


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


def build_engagements(rows) -> list[dict]:
    """Привлечения одним проходом — договоры одним вызовом на весь список."""
    rows = list(rows)
    agreements = _contracts_briefs(
        contracts.get_agreements_brief,
        {row.agreement_id for row in rows if row.agreement_id},
        site="tasks.contractors.agreement_brief",
        what="привлечения без карточки договора")
    out = []
    for row in rows:
        agreement = agreements.get(row.agreement_id)
        out.append({
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
            "agreement_id": row.agreement_id,
            "agreement": (
                {key: agreement[key] for key in
                 ("id", "number", "name", "status", "approval_state")}
                if agreement is not None else None),
            "scope": row.scope,
            "start_date": str(row.start_date) if row.start_date else None,
            "end_date": str(row.end_date) if row.end_date else None,
            "is_active": row.is_active,
            "created_at": str(row.created_at),
            "updated_at": str(row.updated_at),
        })
    return out


def build_engagement(row: ContractorEngagement) -> dict:
    return build_engagements([row])[0]


__all__ = [
    "ContractorInUse", "CounterpartyLinkConflict",
    "list_contractors", "get_contractor", "create_contractor",
    "update_contractor", "delete_contractor",
    "link_counterparty", "unlink_counterparty",
    "list_workers", "get_worker", "create_worker", "update_worker",
    "delete_worker",
    "list_engagements", "get_engagement", "create_engagement",
    "update_engagement", "delete_engagement", "engagement_site_ids",
    "effective_contractors",
    "build_contractor", "build_contractors", "build_worker",
    "build_engagement", "build_engagements",
]
