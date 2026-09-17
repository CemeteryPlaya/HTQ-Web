"""Публичный API аппки hr для ДРУГИХ аппок (контракт PLAN.md §7).

Производитель: Поток A. Потребители: apps.tasks (отдел проекта),
apps.approvals (assignee_resolver). Прямой импорт apps.hr.models /
apps.hr.services из другой аппки запрещён и ловится
apps/core/tests/test_app_isolation.py — только через этот модуль.

Сигнатуры зафиксированы (менять только совместно A↔B). Каждая функция
начинается с require_service("hr"): если аппка выключена, вызывающий получает
ServiceDisabled (api_view → 503), а не молчаливый неверный ответ.

Возвращаются простые словари, а не ORM-объекты: сосед не должен зависеть от
внутренней модели hr.
"""
from __future__ import annotations

from datetime import date

from apps.core.services import require_service

from apps.hr.models import Department, Employee, EmployeeStatus, Position
from apps.users import interface as users

_BRIEF_FIELDS = ("id", "name", "path", "is_active")


def get_department_brief(department_id: int) -> dict | None:
    require_service("hr")
    return Department.objects.filter(id=department_id).values(*_BRIEF_FIELDS).first()


def get_departments_brief(department_ids: list[int]) -> list[dict]:
    require_service("hr")
    ids = list(department_ids)
    if not ids:
        return []
    return list(Department.objects.filter(id__in=ids).values(*_BRIEF_FIELDS))


def get_employee_brief(user_id: int) -> dict | None:
    """Карточка сотрудника по user_id из JWT. Мягко удалённые не отдаются."""
    require_service("hr")
    row = (
        Employee.objects.filter(user_id=user_id, is_deleted=False)
        .values("id", "first_name", "last_name", "department_id",
                "position_id", "position__title", "status",
                "position__is_manager", "position__external_hierarchy",
                "position__serves_subsidiaries")
        .first()
    )
    if row is None:
        return None
    return {
        "id": row["id"],
        "full_name": f"{row['last_name']} {row['first_name']}",
        "department_id": row["department_id"],
        # Единственный шов стадии 2 с кадровым доменом: apps.access ключует
        # роли на должности и обязана получать её id, а не заголовок
        # (спека docs/plans/2026-08-29-stage2-access-and-roles-spec.md, §1.5).
        # Ключ добавлен АДДИТИВНО — остальные читает действующий фронт.
        "position_id": row["position_id"],
        "position_title": row["position__title"],
        # Второй шов стадии 2 с кадровым доменом: внешнюю иерархию включают
        # два поля ДОЛЖНОСТИ, а читает их apps.access, который моделей HR не
        # импортирует (apps/access/services/hierarchy.py::_is_external_manager).
        # Ключи добавлены АДДИТИВНО — остальные читает действующий фронт.
        "is_manager": row["position__is_manager"],
        "external_hierarchy": row["position__external_hierarchy"],
        # Третий шов: «обслуживает дочерние компании» — читает apps.access
        # (roadmap §5.C), тем же способом, что и пара полей внешней иерархии
        # выше. Ключ добавлен АДДИТИВНО — остальные читает действующий фронт.
        "serves_subsidiaries": row["position__serves_subsidiaries"],
        "status": row["status"],
    }


def user_has_permission(user_id: int, permission: str) -> bool:
    """Есть ли у сотрудника явное право его должности.

    Предметные аппки не должны угадывать роль по названию должности
    («Бухгалтер») или импортировать ``Employee``/``Position`` напрямую.
    Они спрашивают эту узкую функцию, а HR остаётся владельцем матрицы
    ``Position.permissions``. Глобальный админ проверяется вызывающей
    аппкой до этого вызова.
    """
    require_service("hr")
    employee = (Employee.objects.filter(user_id=user_id, is_deleted=False)
                .select_related("position").first())
    if employee is None:
        return False
    raw = employee.position.permissions
    if not isinstance(raw, dict):
        return False
    permissions = raw.get("permissions")
    return isinstance(permissions, list) and permission in permissions


def list_departments_brief(limit: int = 500) -> list[dict]:
    """Все отделы разом — для наполнения и админских выборок.

    ``get_departments_brief`` требует список id, которого у вызывающего
    может не быть: команде наполнения apps.tasks нужно разложить проекты
    по РЕАЛЬНЫМ отделам, а какие они — она узнаёт только отсюда.
    """
    require_service("hr")
    return list(
        Department.objects.order_by("path").values(*_BRIEF_FIELDS)[:limit]
    )


def list_employees_brief(limit: int = 500) -> list[dict]:
    """Действующие сотрудники: кто они, в каком отделе и есть ли учётка.

    ``user_id`` отдаётся намеренно: в apps.tasks исполнитель задачи,
    владелец проекта и руководитель объекта — это ИМЕННО user_id (их имена
    резолвит apps.users), а не PK строки Employee. Без этого поля сосед не
    может связать сотрудника с задачей и вынужден был бы лезть в модели hr
    напрямую.
    """
    require_service("hr")
    rows = (
        Employee.objects.filter(is_deleted=False)
        .select_related("position")
        .order_by("last_name", "first_name")
        .values("id", "first_name", "last_name", "email", "user_id",
                "department_id", "position__title", "status")[:limit]
    )
    return [
        {
            "id": row["id"],
            "full_name": f"{row['last_name']} {row['first_name']}".strip(),
            "email": row["email"],
            "user_id": row["user_id"],
            "department_id": row["department_id"],
            "position_title": row["position__title"],
            "status": row["status"],
        }
        for row in rows
    ]


def get_positions_brief(position_ids: list[int]) -> list[dict]:
    """Position directory for a neighbouring app's configuration screen.

    A signoff route stores a position, never an employee or platform account.
    Inactive positions are returned too: an administrator must be able to see
    and repair an old route rather than have its reference disappear from the
    editor.

    ``serves_subsidiaries`` was added additively (block C, task 7): apps.access
    already knows a position's *own* serving flag one at a time via
    ``get_employee_brief`` (``inheritance.inherit``); the external-holders
    listing (``apps.access.services.holders.external_holders``) instead starts
    from a batch of position ids that already hold a granted role
    (``PositionRole``) and needs the flag for all of them at once, without a
    second bespoke bulk function. Existing callers destructure specific keys
    and are unaffected by the extra one.
    """
    require_service("hr")
    ids = list(dict.fromkeys(position_ids))
    if not ids:
        return []
    rows = (Position.objects.filter(id__in=ids).select_related("department")
            .values("id", "title", "department__name", "is_active",
                    "serves_subsidiaries"))
    return [
        {
            "id": row["id"],
            "title": row["title"],
            "department_name": row["department__name"],
            "is_active": row["is_active"],
            "serves_subsidiaries": row["serves_subsidiaries"],
        }
        for row in rows
    ]


def list_positions_hr_levels() -> list[dict]:
    """Должности текущей компании плюс их HR-уровень — для переноса ролей.

    Единственный потребитель — ``apps.access`` (команда переноса кадровых
    уровней в роли должностей, ``access_backfill_positions``, блок I задача
    2): сама эвристика уровня (``apps.hr.access.classify_hr_level``) — это
    HR-домен, и соседняя аппка не вправе ни импортировать её напрямую
    (``apps/core/tests/test_app_isolation.py``), ни повторить у себя — риск
    задачи явно требует не изобретать свою эвристику.

    Без лимита/пагинации НАМЕРЕННО (раунд правок 1 задачи 2): единственный
    вызывающий — одноразовый перенос данных, и для него полнота — это
    единственная гарантия, ради которой он написан. Обрезанный молча список
    напечатал бы честную на вид сводку по НЕПОЛНОМУ множеству должностей —
    перенос выглядел бы завершённым, не будучи им. Функция внутренняя
    (``apps.hr.interface``, не публичный HTTP-путь), зовётся один раз за
    прогон команды на одну компанию — постранично тут нечего разбивать.

    ``hr_level`` каждой должности посчитан ТЕМ ЖЕ порядком, что
    ``resolve_hr_access`` резолвит его для живого токена:

    1. Явный ``Position.permissions["hr_level"]`` — действует и без
       держателя вовсе (должность ещё не занята, но уровень уже назначен).
    2. Иначе — один из держателей должности (действующая, не мягко
       удалённая запись ``Employee``; при нескольких — первый по ``id``,
       детерминированно) и по НЕЙ ``classify_hr_level``, которая сама
       повторяет п.1 для карточки держателя и только потом падает на
       эвристику по названию должности/отдела — тот же порядок, что видит
       обычный запрос.

    ``None``, если ни explicit-переопределения, ни держателя, по которому
    угадать, нет — перенос не должен выдумывать доступ там, где сегодня его
    ни у кого нет.

    ``divergent``/``holder_levels`` (раунд правок 1 задачи 2): ``Employee.
    department`` — независимый FK, не связанный с ``Position.department``, а
    ``classify_hr_level`` смотрит в том числе на отдел ДЕРЖАТЕЛЯ — то есть
    сегодня, при живом резолве, два держателя ОДНОЙ должности МОГУТ иметь
    разные уровни, каждый по своей карточке. Перенос ставит должности ОДНУ
    роль (по правилу «первый держатель по id» — правило не меняется), но обязан
    сделать расхождение ВИДИМЫМ, а не проглотить его: ``divergent=True`` и
    ``holder_levels`` (отсортированный кортеж всех различных уровней,
    встретившихся среди держателей этой должности, включая ``None``) — если
    и только если у должности больше одного держателя и они дают больше
    одного различного уровня. Пусто/``False`` иначе — в т.ч. всегда при
    explicit-переопределении: оно не зависит от держателя, поэтому все
    держатели такой должности неизбежно дают один и тот же уровень.

    Действует в контексте ТЕКУЩЕЙ компании, как ``substitutes_for``/
    ``participant_position``: вызывающий сам входит в схему нужной компании
    через ``htqweb.tenancy.db.use_company``.
    """
    require_service("hr")
    from apps.hr.access import _level_from_permissions, classify_hr_level

    positions = list(Position.objects.all().order_by("id"))
    if not positions:
        return []

    holders_by_position: dict[int, list[Employee]] = {}
    holders = (
        Employee.objects.filter(
            is_deleted=False, position_id__in=[p.id for p in positions],
        )
        .select_related("department", "position")
        .order_by("position_id", "id")
    )
    for employee in holders:
        holders_by_position.setdefault(employee.position_id, []).append(employee)

    result = []
    for position in positions:
        position_holders = holders_by_position.get(position.id, [])
        if position_holders:
            level = classify_hr_level(position_holders[0])
            holder_levels = tuple(sorted(
                {classify_hr_level(holder) for holder in position_holders},
                key=lambda value: (value is None, value),
            ))
        else:
            level = _level_from_permissions(position)
            holder_levels = ()

        divergent = len(holder_levels) > 1
        result.append({
            "id": position.id,
            "title": position.title,
            "is_active": position.is_active,
            "hr_level": level,
            "divergent": divergent,
            "holder_levels": holder_levels if divergent else (),
        })
    return result


def resolve_position_users(position_ids: list[int]) -> dict[int, list[int]]:
    """Resolve HR positions to their current, usable platform accounts.

    The answer deliberately contains only employees who are active, not soft
    deleted, linked to an account, and whose account is active.  This keeps a
    route declarative ("financial controller") while a live approval task
    remains attributable to one concrete JWT identity.
    """
    require_service("hr")
    ids = list(dict.fromkeys(position_ids))
    if not ids:
        return {}

    rows = list(
        Employee.objects.filter(
            position_id__in=ids,
            status=EmployeeStatus.ACTIVE,
            is_deleted=False,
            user_id__isnull=False,
            position__is_active=True,
        ).values("position_id", "user_id")
    )
    briefs = {row["id"]: row for row in users.get_users_brief(
        [row["user_id"] for row in rows]
    )}
    resolved: dict[int, list[int]] = {position_id: [] for position_id in ids}
    for row in rows:
        brief = briefs.get(row["user_id"])
        if brief and brief.get("is_active"):
            resolved[row["position_id"]].append(row["user_id"])
    return resolved


def link_employee_user(employee_id: int, user_id: int) -> bool:
    """Привязать платформенную учётку к карточке сотрудника.

    Запись, а не чтение — единственная в этом модуле. Нужна потому, что
    учётки заводит apps.users (там живёт admin_service с проверками
    уникальности и хешированием пароля), а колонка ``Employee.user_id``
    принадлежит hr, и писать в неё сосед не вправе.

    Возвращает False, если сотрудника нет или учётка уже занята другим —
    ``user_id`` уникален, и молча переклеивать её с одного человека на
    другого нельзя.

    Сама проверка живёт в ``employee_prefill_service.link_user``: туда же
    ходит HR-форма («подтянуть данные из учётки»), и две реализации правила
    «занятую учётку не переклеиваем» разъехались бы неизбежно — ценой в две
    карточки на одного человека.
    """
    require_service("hr")
    from apps.hr.services.employee_prefill_service import link_user

    return link_user(employee_id, user_id)


def org_ancestors(department_id: int) -> list[dict]:
    """Предки отдела от корня к непосредственному родителю (себя НЕ включая).

    D1 плана: ``path`` — строковый путь вида ``"it.dev.backend"``, а не PG-ltree,
    поэтому предки — это его префиксы (``"it"``, ``"it.dev"``). Берём их одним
    запросом ``path__in``, без рекурсии и без обращения к БД на каждый уровень.
    Порядок результата — от корня вниз (важен для assignee_resolver approvals:
    он поднимается по цепочке согласующих).
    """
    require_service("hr")
    dep = Department.objects.filter(id=department_id).values("path").first()
    if dep is None:
        return []
    parts = dep["path"].split(".")
    prefixes = [".".join(parts[:i]) for i in range(1, len(parts))]
    if not prefixes:
        return []
    by_path = {
        d["path"]: d
        for d in Department.objects.filter(path__in=prefixes).values(*_BRIEF_FIELDS)
    }
    return [by_path[p] for p in prefixes if p in by_path]


def notice_user_profile_changed(user_id: int) -> None:
    """Сосед (apps.users) сообщает, что профиль изменился — обновляем копию.

    Вызывается ПОСЛЕ сохранения профиля. Ничего не возвращает: аккаунт —
    владелец идентичности (спека 2026-05-29 §6), и кадровая копия обязана
    догнать его, а не наоборот. Если сотрудника с таким аккаунтом нет —
    обновлять нечего, это нормальный случай (аккаунт админа, внешний
    пользователь).
    """
    require_service("hr")
    from apps.hr.services import identity_sync_service

    employee_id = (Employee.objects
                   .filter(user_id=user_id, is_deleted=False)
                   .values_list("id", flat=True)
                   .first())
    if employee_id is None:
        return
    identity_sync_service.sync_employee(employee_id)


def substitutes_for(position_id: int, on_date: date | None = None) -> list[dict]:
    """Кто по регламенту замещает эту должность на эту дату (HR-FRM-006).

    Контракт для соседнего домена, зафиксированный в
    docs/plans/2026-09-14-group-structure-roadmap.md §6.1: РОВНО три ключа —
    ``position_id`` (должность замещающего), ``kind`` (``primary``/``reserve``),
    ``basis`` (чем оформлено: «Приказ ГД», «Приказ ГД; доверенность на банк»).
    Форма согласована с разработчиком signoff; расширять её в одиночку
    нельзя — лишний ключ здесь становится лишним ключом в чужом коде.

    Отвечает на вопрос «кто ВПРАВЕ подменить», а не «кто подменяет прямо
    сейчас»: отсутствие держателя (отпуск, болезнь) домен `hr` не
    моделирует вовсе, и решение «пора ли звать замещающего» принимает
    вызывающий.

    Действует в контексте ТЕКУЩЕЙ компании, как и остальные функции этого
    модуля: матрица замещения лежит в схеме компании. Чтобы спросить про
    должность другой компании, вызывающий сам входит в её схему через
    ``htqweb.tenancy.db.use_company`` — так же, как он уже делает ради
    ``get_positions_brief``.

    Неизвестная должность — пустой список, а не ошибка: «в этой компании
    такой должности нет» и «замещающих не назначено» для потребителя один и
    тот же ответ «звать некого».
    """
    require_service("hr")
    from apps.hr.services import substitution_service

    rows = substitution_service.active_for_position(position_id, on_date or date.today())
    return [{"position_id": row.substitute_position_id,
             "kind": row.kind,
             "basis": row.basis}
            for row in rows]


def participant_position() -> dict | None:
    """Должность «Участник (ОСУ)» в ТЕКУЩЕЙ компании — или ``None``.

    Общее собрание участников утверждает назначение директора ДО, бюджет
    группы и крупные сделки (HR-FRM-004, п. 7, 11, 14); маршрут
    согласования ссылается на него обычным ``position_id`` — этим и берёт.
    Держателей резолвит ``resolve_position_users``, как для любой должности.

    Сосед не хардкодит название: оно закреплено ``is_system``, но знать его
    соседу незачем. ``None`` — законный ответ: у дочерних компаний органа
    владельцев в платформе нет, там «участник» — сам холдинг, и решение
    принимает его генеральный директор (кросс-компанейский этап, roadmap §6.2).

    Ровно три ключа — форма закреплена в roadmap §6.1.
    """
    require_service("hr")
    from apps.hr.services import participant_service

    position = participant_service.find_participant()
    if position is None:
        return None
    return {"id": position.id, "title": position.title,
            "is_active": position.is_active}
