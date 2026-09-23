"""Выдача ролей: должности (штатный путь) и лично пользователю (исключение).

⚠️ Каждая выборка здесь несёт ``company_slug``. Таблицы лежат в ``public``, и
``search_path`` их НЕ изолирует: замена набора без фильтра стёрла бы
назначения соседней компании, не выглядя ошибкой (спека §1.3, риск 3).
Сторож — ``apps/access/tests/test_guards.py``.
"""

from __future__ import annotations

from django.db import transaction

from apps.access.models import (
    POSITION_ROLE_SCOPE_KINDS, PositionRole, Role, RoleAssignment, ScopeKind,
)
from apps.access.services.errors import RoleNotInCompany, ScopeInvalid, UnknownRole


def assert_role_belongs(company: str, role: Role) -> None:
    """Роль компании видна и выдаётся только в ней (блок I.2, R2).

    Общая роль (``company_slug`` пуст) выдаётся в любой компании — проверка
    для неё тривиальна. Именная роль другой компании (``hr-custom-*``, но не
    только — поле общее для любой будущей роли одной компании) — нет.
    """
    if role.company_slug and role.company_slug != company:
        raise RoleNotInCompany(
            f"роль {role.code!r} принадлежит компании {role.company_slug!r}"
        )


def _check_roles_exist(role_ids: list[int]) -> None:
    wanted = set(role_ids)
    if not wanted:
        return
    known = set(Role.objects.filter(id__in=wanted).values_list("id", flat=True))
    missing = sorted(wanted - known)
    if missing:
        raise UnknownRole(f"нет таких ролей: {missing}")


def position_roles(company: str, position_id: int) -> list[dict]:
    return [
        {"role_id": row["role_id"], "code": row["role__code"], "title": row["role__title"]}
        for row in (PositionRole.objects
                    .filter(company_slug=company, position_id=position_id)
                    .order_by("role__title")
                    .values("role_id", "role__code", "role__title"))
    ]


def set_position_roles(company: str, position_id: int, role_ids: list[int]) -> None:
    """Замена набора ролей должности целиком (спека §4.3)."""
    unique_ids = list(dict.fromkeys(role_ids))
    _check_roles_exist(unique_ids)
    for role in Role.objects.filter(id__in=unique_ids):
        assert_role_belongs(company, role)
    with transaction.atomic():
        PositionRole.objects.filter(
            company_slug=company, position_id=position_id).delete()
        PositionRole.objects.bulk_create([
            PositionRole(company_slug=company, position_id=position_id, role_id=rid)
            for rid in unique_ids
        ])


def ensure_position_role(company: str, position_id: int, role_code: str,
                         scope_kind: str) -> bool:
    """Добавить должности ОДНУ системную роль, не трогая остальные. Идемпотентно.

    Задача 11 блока I — для сидов (``seed_hr_demo`` раскладывает
    ``Post.hr_level`` структур в роли должностей) и любого другого кода,
    которому нужно ровно то, что сделал бы администратор после переноса:
    «у этой должности есть эта роль с этой областью». Отличается от
    ``set_position_roles`` по двум пунктам, и оба — принципиальные:

    * НЕ заменяет набор ролей должности целиком — роль, выданная кадровиком
      руками, остаётся; ``set_position_roles`` её стёр бы;
    * принимает ``scope_kind`` — штатный API его не знает (см. докстринг
      ``PositionRole``), а сиду нужна область «свой отдел» для младших
      уровней, иначе ``hr-junior`` на стенде видел бы всю компанию.

    Роль ищется ПО КОДУ и ТОЛЬКО среди системных: коды ``hr-*``/
    ``employee-basic`` сеют миграции ``access/0004``–``0005``, и подставить
    вместо них одноимённую пользовательскую роль (каталог общий, коды
    уникальны, но ``is_system`` — единственная гарантия, что за кодом стоит
    именно засеянный набор) сид не должен. Отсутствие — ``UnknownRole`` с
    указанием на миграцию, а не молчаливый пропуск.

    Уже существующая связь с ДРУГИМ ``scope_kind`` не переписывается — тот
    же принцип, что у ``access_backfill_positions``: перенос и сид не
    отменяют решение человека. Возвращает ``True``, если связь создана
    сейчас, ``False`` — если уже была.
    """
    allowed = {kind for kind, _label in POSITION_ROLE_SCOPE_KINDS}
    if scope_kind not in allowed:
        raise ScopeInvalid(
            f"область {scope_kind!r} недопустима для роли должности; "
            f"допустимы: {sorted(allowed)}"
        )
    role = Role.objects.filter(code=role_code, is_system=True).first()
    if role is None:
        raise UnknownRole(
            f"системной роли {role_code!r} нет в реестре (миграции "
            f"access.0004/0005 не применены?)"
        )
    assert_role_belongs(company, role)
    _row, created = PositionRole.objects.get_or_create(
        company_slug=company, position_id=position_id, role=role,
        defaults={"scope_kind": scope_kind},
    )
    return created


#: Код базовой роли из ``access/0004_seed_employee_role`` — тот же литерал,
#: что ``access_backfill_basic.ROLE_CODE`` (сверяет
#: ``apps/access/tests/test_basic_role_on_membership.py``).
BASIC_ROLE_CODE = "employee-basic"


def ensure_basic_role(company: str, user_id: int) -> bool:
    """Выдать участнику компании базовую роль — идемпотентно (рулинг M).

    ``employee-basic`` (``access/0004``) — «шаблон дня приёма»: профиль,
    подбор коллег, задачи, ежедневка. ``access_backfill_basic`` раздал её
    тем, кто был участником на день выкатки; эта функция выдаёт её каждому
    НОВОМУ участнику в момент создания членства
    (``apps.companies.services.membership_service.grant_membership``) — иначе
    новый человек получал бы 403 на ``users/options`` и весь ``tasks``.

    Область ``COMPANY`` (почему не отдел — докстринг
    ``access_backfill_basic``). Личное назначение, а не роль должности:
    базовый доступ есть у участника, а не у штатной единицы, и у человека
    без кадровой карточки тоже. Уже существующее назначение не трогается.
    Роли нет в каталоге — ``UnknownRole``: членство без базового доступа
    хуже громкой ошибки выкатки (миграции ``access`` не применены).
    Возвращает ``True``, если назначение создано сейчас.
    """
    role = Role.objects.filter(code=BASIC_ROLE_CODE, is_system=True).first()
    if role is None:
        raise UnknownRole(
            f"системной роли {BASIC_ROLE_CODE!r} нет в реестре (миграция "
            f"access.0004 не применена?)"
        )
    # Тривиально: employee-basic — общая роль (company_slug пуст). Проверка
    # стоит ради единообразия со всеми остальными путями выдачи (блок I.2).
    assert_role_belongs(company, role)
    _row, created = RoleAssignment.objects.get_or_create(
        company_slug=company, user_id=user_id, role=role,
        scope_kind=ScopeKind.COMPANY, scope_id=None,
    )
    return created


def _check_scope(item: dict) -> None:
    kind, scope_id = item.get("scope_kind"), item.get("scope_id")
    if kind not in ScopeKind.values:
        raise ScopeInvalid(f"неизвестная область: {kind!r}")
    if kind == ScopeKind.COMPANY and scope_id is not None:
        raise ScopeInvalid("область «компания» не имеет идентификатора")
    if kind != ScopeKind.COMPANY and scope_id is None:
        raise ScopeInvalid(f"область {kind!r} требует scope_id")


def user_assignments(company: str, user_id: int) -> list[dict]:
    return [
        {"role_id": row["role_id"], "scope_kind": row["scope_kind"],
         "scope_id": row["scope_id"]}
        for row in (RoleAssignment.objects
                    .filter(company_slug=company, user_id=user_id)
                    .order_by("role_id", "scope_kind")
                    .values("role_id", "scope_kind", "scope_id"))
    ]


def set_user_assignments(company: str, user_id: int, items: list[dict]) -> None:
    """Замена личных назначений целиком (спека §4.4).

    Исключительный путь: не-сотрудники, исполняющие обязанности, временные
    расширения. Штатный — роли должности.
    """
    for item in items:
        _check_scope(item)
    role_ids = [i["role_id"] for i in items]
    _check_roles_exist(role_ids)
    for role in Role.objects.filter(id__in=role_ids):
        assert_role_belongs(company, role)

    seen: set[tuple] = set()
    rows: list[RoleAssignment] = []
    for item in items:
        key = (item["role_id"], item["scope_kind"], item["scope_id"])
        if key in seen:
            continue
        seen.add(key)
        rows.append(RoleAssignment(
            company_slug=company, user_id=user_id, role_id=item["role_id"],
            scope_kind=item["scope_kind"], scope_id=item["scope_id"],
        ))

    with transaction.atomic():
        RoleAssignment.objects.filter(company_slug=company, user_id=user_id).delete()
        RoleAssignment.objects.bulk_create(rows)
