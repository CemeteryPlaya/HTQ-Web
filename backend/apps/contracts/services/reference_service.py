"""Справочники модуля: страны, программы, администраторы бюджета.

Тонкий CRUD без собственной бизнес-логики — вся арифметика бюджета живёт в
``budget_calc``/``budget_service``. Единственное общее правило, которое
здесь соблюдается: все FK — ``PROTECT``, поэтому удаление справочной записи,
на которую кто-то ссылается, отдаёт 409, а не роняет 500 из глубины ORM.
"""

from __future__ import annotations

from contextlib import contextmanager

from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.http import Http404

from apps.contracts.models import Administrator, Country, Program
from apps.tasks import interface as tasks


class ReferenceConflict(Exception):
    """Нарушение уникальности или попытка удалить используемую запись."""


# ── Country ─────────────────────────────────────────────────────────────

def list_countries():
    return list(Country.objects.all())


def get_country_or_404(country_id: int) -> Country:
    country = Country.objects.filter(pk=country_id).first()
    if country is None:
        raise Http404("Страна не найдена")
    return country


def create_country(*, name: str, iso_code: str = "") -> Country:
    with conflict_as(f"Страна «{name}» уже существует"):
        return Country.objects.create(name=name, iso_code=iso_code)


def resolve_country_input(data) -> Country:
    """``schemas.CountryInput`` → запись ``Country``: по ``id`` либо
    get_or_create по названию.

    Живёт здесь, а не в budget_service, потому что потребителей два —
    составная заявка на бюджет и составная карточка контрагента, и обе
    должны схлопывать одинаковые названия в одну страну. Двое заполняющих,
    независимо вписавших «Казахстан», обязаны получить одну запись, а не
    две одинаковые.
    """
    if data.id is not None:
        return get_country_or_404(data.id)
    country, _ = Country.objects.get_or_create(
        name=data.name.strip(), defaults={"iso_code": data.iso_code},
    )
    return country


def update_country(country_id: int, **fields) -> Country:
    country = get_country_or_404(country_id)
    return _apply(country, fields, conflict=f"Страна «{fields.get('name')}» уже существует")


def delete_country(country_id: int) -> None:
    delete_protected(get_country_or_404(country_id),
                     "Страна используется администратором или контрагентом")


# ── Program ─────────────────────────────────────────────────────────────

def list_programs(*, is_active: bool | None = None):
    query = Program.objects.all()
    if is_active is not None:
        query = query.filter(is_active=is_active)
    return list(query)


def get_program_or_404(program_id: int) -> Program:
    program = Program.objects.filter(pk=program_id).first()
    if program is None:
        raise Http404("Программа не найдена")
    return program


def create_program(*, name: str, expense_item: str, code: str = "",
                   is_active: bool = True) -> Program:
    with conflict_as(f"Программа «{name} / {expense_item}» уже существует"):
        return Program.objects.create(name=name, expense_item=expense_item,
                                      code=code, is_active=is_active)


def update_program(program_id: int, **fields) -> Program:
    return _apply(get_program_or_404(program_id), fields,
                  conflict="Такая пара «программа / статья расходов» уже существует")


def delete_program(program_id: int) -> None:
    delete_protected(get_program_or_404(program_id),
                     "Программа используется бюджетной строкой — снимите is_active "
                     "вместо удаления")


# ── Administrator ───────────────────────────────────────────────────────

def resolve_project_or_404(project_id: int) -> dict:
    """Паспорт проекта из ``apps.tasks`` либо 404.

    Проверяется ЯВНО, по той же причине, по которой ``create_administrator``
    проверяет страну: несуществующий ``project_id`` — это обычная опечатка
    клиента, и она должна быть честной 404 про проект, а не тихо записанным
    в базу мусором. FK бы это поймал, но междоменный FK запрещён, поэтому
    целостность связи держится здесь.
    """
    brief = tasks.get_project_brief(project_id)
    if brief is None:
        raise Http404(f"Проект {project_id} не найден в модуле задач")
    return brief


def _sync_project_name(admin: Administrator, brief: dict | None) -> None:
    """Подпись записи следует за названием связанного проекта.

    Без этого одно и то же название осталось бы в платформе дважды и
    разъехалось при первой переименовке проекта — ровно та беда, ради
    которой связь и заводилась.
    """
    if brief is not None:
        admin.project_name = brief["name"]


def attach_projects(admins: list[Administrator]) -> list[Administrator]:
    """Проставить каждому администратору его ``project`` одним запросом.

    Пакетно, а не поштучно: страница бюджетов показывает все записи разом, и
    ``get_project_brief`` на каждую превратил бы её в N+1.

    Результат кладётся АТРИБУТОМ на объект, потому что ``AdministratorRead``
    собирается из ORM-строки (``from_attributes``) — так поле доезжает до
    схемы без отдельного слоя сериализации, которого у справочников нет.

    Проект, который удалили в модуле задач, просто не найдётся: связь
    останется в базе, а в ответе будет ``None``. Это осознанно — стирать
    ссылку в чужой транзакции некому, а «проект был, но его больше нет» и
    «проекта не указывали» интерфейс различает по ``project_id``.
    """
    ids = [a.project_id for a in admins if a.project_id]
    by_id = {row["id"]: row for row in tasks.get_projects_brief(ids)} if ids else {}
    for admin in admins:
        admin.project = by_id.get(admin.project_id) if admin.project_id else None
    return admins


def list_administrators(*, is_active: bool | None = None, country_id: int | None = None):
    query = Administrator.objects.select_related("country")
    if is_active is not None:
        query = query.filter(is_active=is_active)
    if country_id is not None:
        query = query.filter(country_id=country_id)
    return attach_projects(list(query))


def get_administrator_or_404(administrator_id: int) -> Administrator:
    admin = Administrator.objects.select_related("country").filter(pk=administrator_id).first()
    if admin is None:
        raise Http404("Администратор бюджета не найден")
    return attach_projects([admin])[0]


def create_administrator(*, country_id: int, project_name: str = "",
                         project_id: int | None = None,
                         user_id: int | None = None,
                         is_active: bool = True) -> Administrator:
    # Существование страны проверяется явно: без этого несуществующий
    # country_id ушёл бы в БД и вернулся IntegrityError → 500, вместо
    # честного 404 про конкретно ненайденную страну.
    # Страна передаётся объектом, а не ``country_id=``: ответ отдаёт
    # ``display_name``/``country_name``, и по объекту они читаются из
    # закэшированной связи, а по id — лишним запросом.
    country = get_country_or_404(country_id)

    # Со связью подпись берётся у проекта, без связи — из присланного текста.
    # Поэтому ``project_name`` больше не обязателен, но пустым остаться не
    # может: он и есть подпись записи (``display_name``, сортировка).
    brief = resolve_project_or_404(project_id) if project_id else None
    if brief is not None:
        project_name = brief["name"]
    if not project_name:
        raise ReferenceConflict(
            "Нужно либо название проекта, либо связь с проектом модуля задач")

    admin = Administrator.objects.create(
        country=country, project_name=project_name, project_id=project_id,
        user_id=user_id, is_active=is_active,
    )
    admin.project = brief
    return admin


def update_administrator(administrator_id: int, **fields) -> Administrator:
    if "country_id" in fields and fields["country_id"] is not None:
        get_country_or_404(fields["country_id"])

    admin = get_administrator_or_404(administrator_id)

    # ``project_id`` обрабатывается ДО ``_apply``: смена связи переписывает и
    # подпись, а ``_apply`` кладёт присланные поля как есть и о таком правиле
    # не знает.
    if "project_id" in fields:
        project_id = fields.pop("project_id")
        if project_id is None:
            # Связь снимают. ``project_name`` остаётся тем, что было, — иначе
            # запись потеряла бы подпись и пропала бы из списков.
            admin.project_id = None
            admin.project = None
            admin.save(update_fields=["project_id", "updated_at"])
        else:
            brief = resolve_project_or_404(project_id)
            admin.project_id = project_id
            _sync_project_name(admin, brief)
            admin.save(update_fields=["project_id", "project_name", "updated_at"])
            admin.project = brief

    return _apply(admin, fields) if fields else admin


def delete_administrator(administrator_id: int) -> None:
    delete_protected(get_administrator_or_404(administrator_id),
                     "У администратора есть бюджетные строки — снимите is_active "
                     "вместо удаления")


# ── Общее ───────────────────────────────────────────────────────────────

@contextmanager
def conflict_as(message: str):
    """Перевести ``IntegrityError`` в ``ReferenceConflict`` (вьюха отдаст 409
    вместо 500), не оставив за собой сломанную транзакцию.

    ``transaction.atomic()`` здесь не декоративный: в Postgres любой
    IntegrityError переводит ТЕКУЩУЮ транзакцию в aborted-состояние, и все
    последующие запросы в ней падают с «current transaction is aborted».
    Без вложенного atomic (savepoint) поймать ошибку и продолжить работу
    нельзя — в проде это первый же запрос после конфликта, в тестах
    (pytest-django оборачивает каждый тест в транзакцию) вообще весь
    остаток теста.
    """
    try:
        with transaction.atomic():
            yield
    except IntegrityError as exc:
        raise ReferenceConflict(message) from exc


def _apply(obj, fields: dict, *, conflict: str = "Нарушено ограничение уникальности"):
    """Записать переданные (не-None) поля и сохранить.

    ``None`` означает «поле не пришло в PATCH», а не «обнулить»: схемы
    обновления объявляют все поля как ``Optional[...] = None``. Обнуляемых
    полей у этих справочников нет, поэтому развилка не нужна.
    """
    changed = [key for key, value in fields.items() if value is not None]
    for key in changed:
        setattr(obj, key, fields[key])
    if changed:
        with conflict_as(conflict):
            obj.save()
    return obj


def delete_protected(obj, message: str) -> None:
    try:
        obj.delete()
    except ProtectedError as exc:
        raise ReferenceConflict(message) from exc
