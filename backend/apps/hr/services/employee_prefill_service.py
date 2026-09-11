"""Перенос уже имеющихся данных в карточку сотрудника.

Задача, которую решает модуль: те же сведения о человеке лежат в платформе
не в одном месте. Учётка (``apps.users``) знает ФИО, телефон, аватар и био;
корпоративный ящик (``apps.mail``) знает рабочий адрес; соседняя карточка
сотрудника знает, в каком отделе и на какой должности сидит тот, кто делает
ту же работу. До этого модуля HR перепечатывал всё это руками, а из учётки
форма создания брала ровно три поля (имя, фамилию, email).

Три вещи, вокруг которых собран весь модуль:

**Источник описывает себя сам.** ``build_prefill`` приводит любой из трёх
источников к одному виду — ``Prefill`` с плоским словарём полей ``Employee``.
Дальше ни ``diff``, ни ``apply_prefill``, ни вьюхи не знают, откуда пришли
данные; добавить четвёртый источник — значит написать одну ``_from_*``
функцию и не трогать больше ничего.

**Заполненное не перезаписывается молча.** ``diff`` метит каждое поле:
``fill`` (у сотрудника пусто — можно просто заполнить), ``conflict``
(значения расходятся — решает человек), ``same`` (переносить нечего). Это
единственная причина, по которой предпросмотр и применение разнесены на два
вызова: сначала показать «было → станет», потом применить ровно то, что
человек отметил.

**Применяется только показанное.** ``apply_prefill`` сверяет запрошенные
поля с тем же ``diff``, который видел человек: поля, которого в предпросмотре
не было, в карточке не окажется, чем бы ни было набито тело запроса.

Модуль — единственное место, где живёт привязка учётки к карточке:
``apps.hr.interface.link_employee_user`` теперь тонкая обёртка над здешней
``link_user``. Две реализации проверки «эта учётка уже занята» разъехались бы
неизбежно, а цена расхождения — две карточки на одного человека.
"""
from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from django.db import transaction

from apps.hr.models import Department, Employee, Position
from apps.hr.services import audit_service, employee_service
from apps.mail import interface as mail_interface
from apps.users import interface as users_interface
from htqweb import phone as phone_utils

SOURCE_USER = "user"
SOURCE_EMPLOYEE = "employee"
SOURCE_MAILBOX = "mailbox"
SOURCE_TYPES = (SOURCE_USER, SOURCE_EMPLOYEE, SOURCE_MAILBOX)

#: Поля, которые вообще могут быть перенесены, в порядке показа в
#: предпросмотре (он же порядок полей формы). Всё, чего здесь нет, не
#: переносится ни одним источником — ``hire_date`` и ``status`` в этом
#: списке отсутствуют намеренно: дата приёма и состояние — это события в
#: жизни КОНКРЕТНОГО человека, а не справочные данные, и «подтянуть» их
#: у коллеги значит записать неправду.
TRANSFERABLE_FIELDS: tuple[str, ...] = (
    "last_name", "first_name", "middle_name", "email", "phone",
    "department_id", "position_id", "avatar_url", "bio", "user_id",
)

#: Поля, смена которых у существующего сотрудника — это перевод, а не
#: правка анкеты. Вьюха требует на них ``can_transfer_employee``, тем же
#: правилом, что и обычный PATCH (apps/hr/views.py::_update_employee).
TRANSFER_FIELDS = frozenset({"department_id", "position_id"})

STATE_FILL = "fill"
STATE_CONFLICT = "conflict"
STATE_SAME = "same"


class SourceNotFound(Exception):
    """404 — источника с таким id нет (или он удалён/недоступен)."""


class UnknownSourceType(Exception):
    """422 — ``type`` вне SOURCE_TYPES."""


class UserAlreadyLinked(Exception):
    """409 — учётка уже привязана к ДРУГОЙ карточке сотрудника."""


class UserNotFound(Exception):
    """422 — ``user_id`` не соответствует ни одной учётке платформы."""


@dataclass(frozen=True)
class Prefill:
    """Источник, приведённый к полям ``Employee``.

    ``title``/``subtitle`` — как показать источник человеку («Иванов Иван» /
    «i.ivanov@htq.group»); дальше по коду они не значат ничего, кроме текста.
    """

    source_type: str
    source_id: int
    title: str
    subtitle: str
    values: dict = dataclass_field(default_factory=dict)


# ── Источники ─────────────────────────────────────────────────────────────

def _clean(value) -> object | None:
    """Пустое значение источника = «нечего предлагать», а не «сотри у себя».

    Без этого пустой телефон в учётке выглядел бы как предложение стереть
    заполненный телефон в карточке.
    """
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


def _pack(pairs: dict) -> dict:
    return {key: cleaned for key, value in pairs.items()
            if (cleaned := _clean(value)) is not None}


def _from_user(user_id: int) -> Prefill:
    data = users_interface.get_user_prefill(user_id)
    if data is None:
        raise SourceNotFound

    return Prefill(
        source_type=SOURCE_USER,
        source_id=user_id,
        title=data["full_name"],
        subtitle=data["email"],
        values=_pack({
            "first_name": data["first_name"],
            "last_name": data["last_name"],
            # patronymic в users == middle_name в hr: одно и то же поле,
            # разные исторические имена колонок.
            "middle_name": data["patronymic"],
            "email": data["email"],
            "phone": data["phone"],
            "avatar_url": data["avatar_url"],
            "bio": data["bio"],
            # Сам факт выбора учётки источником — это и предложение её
            # привязать: карточка без user_id не пустит человека в /me/.
            "user_id": data["id"],
        }),
    )


def _from_employee(employee_id: int) -> Prefill:
    """Соседняя карточка как ШАБЛОН — только место в оргструктуре.

    Личные данные отсюда не берутся сознательно: «такой же, как Петров»
    осмысленно ровно до фамилии и телефона. Поэтому источник отдаёт два
    поля, и оба справочные.
    """
    employee = (
        Employee.objects.filter(id=employee_id, is_deleted=False)
        .select_related("department", "position")
        .first()
    )
    if employee is None:
        raise SourceNotFound

    full_name = " ".join(
        part for part in (employee.last_name, employee.first_name, employee.middle_name) if part
    )
    position_title = employee.position.title if employee.position_id else ""
    department_name = employee.department.name if employee.department_id else ""
    return Prefill(
        source_type=SOURCE_EMPLOYEE,
        source_id=employee_id,
        title=full_name or employee.email,
        subtitle=" · ".join(part for part in (position_title, department_name) if part),
        values=_pack({
            "department_id": employee.department_id,
            "position_id": employee.position_id,
        }),
    )


def _split_display_name(display_name: str) -> tuple[str, str]:
    """``display_name`` ящика → (имя, фамилия); ('', '') если не разбирается.

    Платформа пишет туда ``"{first_name} {last_name}"``
    (``mailbox_service.provision``), поэтому два слова читаются однозначно.
    Три и больше не трогаем: почтовый администратор мог завести ящик мимо
    платформы и написать что угодно («Отдел продаж», «Иванов Иван
    Иванович»), а угадывать порядок слов в чужой строке — способ тихо
    записать в карточку неправду. Ценность этого источника всё равно в
    адресе, а не в имени.
    """
    parts = (display_name or "").split()
    if len(parts) != 2:
        return "", ""
    return parts[0], parts[1]


def _from_mailbox(mailbox_id: int) -> Prefill:
    data = mail_interface.get_mailbox_brief(mailbox_id)
    if data is None:
        raise SourceNotFound

    first_name, last_name = _split_display_name(data["display_name"])
    return Prefill(
        source_type=SOURCE_MAILBOX,
        source_id=mailbox_id,
        title=data["address"],
        subtitle=data["display_name"] or "",
        values=_pack({
            "email": data["address"],
            "first_name": first_name,
            "last_name": last_name,
            # Ящик уже за кем-то закреплён — значит источник знает и учётку.
            "user_id": data["user_id"],
        }),
    )


def build_prefill(source_type: str, source_id: int) -> Prefill:
    if source_type == SOURCE_USER:
        return _from_user(source_id)
    if source_type == SOURCE_EMPLOYEE:
        return _from_employee(source_id)
    if source_type == SOURCE_MAILBOX:
        return _from_mailbox(source_id)
    raise UnknownSourceType


# ── Предпросмотр ──────────────────────────────────────────────────────────

def _display(field: str, value) -> str:
    """Человекочитаемое значение поля — id справочников разворачиваются.

    Предпросмотр «department_id: 3 → 7» не сообщает ничего; названия
    отделов сообщают.
    """
    if value in (None, ""):
        return ""
    if field == "department_id":
        name = Department.objects.filter(id=value).values_list("name", flat=True).first()
        return name or f"#{value}"
    if field == "position_id":
        title = Position.objects.filter(id=value).values_list("title", flat=True).first()
        return title or f"#{value}"
    if field == "user_id":
        brief = users_interface.get_user_brief(value)
        return brief["full_name"] if brief else f"#{value}"
    return str(value)


def _same(current, incoming) -> bool:
    if isinstance(current, str) and isinstance(incoming, str):
        return current.strip().lower() == incoming.strip().lower()
    return current == incoming


def diff(employee: Employee | None, prefill: Prefill) -> list[dict]:
    """Построчный «было → станет» для полей, которые источник может дать.

    ``employee=None`` — карточку ещё создают, сравнивать не с чем: все поля
    ``fill``. Порядок строк — ``TRANSFERABLE_FIELDS``, а не порядок словаря:
    предпросмотр должен читаться сверху вниз как форма, а не как дамп.
    """
    rows: list[dict] = []
    for field in TRANSFERABLE_FIELDS:
        if field not in prefill.values:
            continue
        incoming = prefill.values[field]
        current = _clean(getattr(employee, field)) if employee is not None else None

        if current is not None and _same(current, incoming):
            state = STATE_SAME
        elif current is None:
            state = STATE_FILL
        else:
            state = STATE_CONFLICT

        rows.append({
            "field": field,
            "current": current,
            "incoming": incoming,
            "current_display": _display(field, current),
            "incoming_display": _display(field, incoming),
            "state": state,
        })
    return rows


def preview(employee: Employee | None, source_type: str, source_id: int) -> dict:
    """Ответ ``POST /employees/prefill`` целиком."""
    prefill = build_prefill(source_type, source_id)
    rows = diff(employee, prefill)
    return {
        "source": {
            "type": prefill.source_type,
            "id": prefill.source_id,
            "title": prefill.title,
            "subtitle": prefill.subtitle,
        },
        "values": prefill.values,
        "fields": rows,
        # Готовые счётчики, чтобы каждому потребителю не пересчитывать
        # одно и то же ради заголовка диалога.
        "fillable": sum(1 for row in rows if row["state"] == STATE_FILL),
        "conflicts": sum(1 for row in rows if row["state"] == STATE_CONFLICT),
    }


# ── Привязка учётки ───────────────────────────────────────────────────────

def link_user(employee_id: int, user_id: int) -> bool:
    """Привязать платформенную учётку к карточке. False — привязать нельзя.

    Единственная реализация в проекте: ``apps.hr.interface.
    link_employee_user`` вызывает её же. Идемпотентна (та же учётка на той
    же карточке — успех, без записи), но НИКОГДА не переклеивает чужую:
    ``Employee.user_id`` уникален, и молчаливый перенос учётки с одного
    человека на другого — это потеря доступа у первого.
    """
    employee = Employee.objects.filter(id=employee_id, is_deleted=False).first()
    if employee is None:
        return False
    if employee.user_id == user_id:
        return True
    if Employee.objects.filter(user_id=user_id).exclude(id=employee_id).exists():
        return False
    employee.user_id = user_id
    employee.save(update_fields=["user_id"])
    return True


def assert_user_available(user_id: int, *, exclude_employee_id: int | None = None) -> None:
    """Учётка существует и свободна — иначе UserNotFound / UserAlreadyLinked.

    Вынесено сюда (а не оставлено на БД-констрейнт ``unique``), потому что
    IntegrityError на входе в API — это 500 и «что-то пошло не так», а
    нужны 422 «нет такой учётки» и 409 «учётка уже за другим сотрудником».
    """
    if users_interface.get_user_brief(user_id) is None:
        raise UserNotFound
    taken = Employee.objects.filter(user_id=user_id)
    if exclude_employee_id is not None:
        taken = taken.exclude(id=exclude_employee_id)
    if taken.exists():
        raise UserAlreadyLinked


# ── Применение ────────────────────────────────────────────────────────────

@transaction.atomic
def apply_prefill(employee_id: int, source_type: str, source_id: int,
                  fields: list[str], *, changed_by_id: int) -> Employee:
    """Записать в карточку ТОЛЬКО перечисленные поля.

    ``fields`` — белый список от человека, но доверяем мы не ему, а
    ``diff``: поле, которого нет в предпросмотре (или которое там помечено
    ``same``), молча отбрасывается. Иначе «применить» могло бы записать
    больше, чем показал экран, — ровно то, чего эта задача и должна была не
    допустить.

    Пустой итоговый набор — не ошибка (человек снял все галочки): карточка
    возвращается как есть, без записи в аудит.
    """
    employee = employee_service.get_employee(employee_id)
    prefill = build_prefill(source_type, source_id)
    rows = {row["field"]: row for row in diff(employee, prefill)}

    requested = list(dict.fromkeys(fields or []))
    selected = [name for name in TRANSFERABLE_FIELDS
                if name in requested and name in rows and rows[name]["state"] != STATE_SAME]
    if not selected:
        return employee

    old_values = {name: rows[name]["current"] for name in selected}
    new_values = {name: rows[name]["incoming"] for name in selected}

    if "email" in new_values:
        email = new_values["email"]
        if email != employee.email and employee_service._email_taken(email):
            raise employee_service.EmailAlreadyInUse
    if "department_id" in new_values:
        employee_service._assert_department_exists(new_values["department_id"])
    if "position_id" in new_values:
        employee_service._assert_position_exists(new_values["position_id"])
    if "user_id" in new_values:
        assert_user_available(new_values["user_id"], exclude_employee_id=employee.id)

    for name, value in new_values.items():
        setattr(employee, name, value)
    employee.save()

    audit_service.log(
        entity_type="employee",
        entity_id=employee.id,
        action="prefill",
        old_values={key: _display(key, value) for key, value in old_values.items()},
        # Источник — часть записи, а не догадка по времени: через год
        # «откуда взялся этот телефон» отвечается только так.
        new_values={
            **{key: _display(key, value) for key, value in new_values.items()},
            "_source": f"{prefill.source_type}:{prefill.source_id}",
        },
        changed_by=changed_by_id,
    )
    return employee_service.get_employee(employee.id)


# ── Подсказка о совпадении ────────────────────────────────────────────────

def _employee_matches(*, email: str, phone: str, first_name: str, last_name: str,
                      exclude_employee_id: int | None, limit: int) -> list[dict]:
    """Уже заведённые карточки, похожие на то, что набрано в форме.

    Зеркало ``users_interface.find_user_matches`` по своей таблице и с теми
    же основаниями (email → телефон → ФИО). Этот список важнее списка
    учёток: он отвечает на вопрос «а не заводим ли мы человека повторно»,
    который до сих пор ловился только уникальностью email — то есть не
    ловился вовсе, стоило человеку сменить почту.
    """
    email_norm = (email or "").strip().lower()
    phone_tail = phone_utils.comparable_tail(phone)
    first = (first_name or "").strip()
    last = (last_name or "").strip()

    probes: list[tuple[str, str, object]] = []
    base = Employee.objects.filter(is_deleted=False)
    if exclude_employee_id is not None:
        base = base.exclude(id=exclude_employee_id)
    if email_norm:
        probes.append(("email", "exact", base.filter(email__iexact=email_norm)))
    if phone_tail:
        probes.append((
            "phone", "exact",
            base.exclude(phone__isnull=True).exclude(phone="")
            .annotate(_phone_digits=phone_utils.digits_expr())
            .filter(_phone_digits__endswith=phone_tail),
        ))
    if first and last:
        probes.append((
            "full_name", "similar",
            base.filter(first_name__iexact=first, last_name__iexact=last),
        ))
    if not probes:
        return []

    found: dict[int, dict] = {}
    order: list[int] = []
    for reason, kind, qs in probes:
        rows = (qs.select_related("department", "position")
                .order_by("last_name", "first_name")[:limit])
        for emp in rows:
            entry = found.get(emp.id)
            if entry is None:
                entry = {
                    "id": emp.id,
                    "full_name": " ".join(
                        part for part in (emp.last_name, emp.first_name, emp.middle_name) if part
                    ) or emp.email,
                    "email": emp.email,
                    "phone": emp.phone,
                    "user_id": emp.user_id,
                    "department_name": emp.department.name if emp.department_id else "",
                    "position_title": emp.position.title if emp.position_id else "",
                    "status": emp.status,
                    "match_on": [],
                    "match_kind": kind,
                }
                found[emp.id] = entry
                order.append(emp.id)
            if reason not in entry["match_on"]:
                entry["match_on"].append(reason)
            if kind == "exact":
                entry["match_kind"] = "exact"

    return [found[emp_id] for emp_id in order[:limit]]


def annotate_employee_links(users: list[dict]) -> list[dict]:
    """Проставить каждой учётке ``employee_id`` — карточку, которая за ней.

    Отдельная функция, потому что вопрос «у этого пользователя уже есть
    карточка?» задают три места сразу: пикер источника, подсказка о
    совпадении и список кандидатов на импорт. Ответ везде должен быть один
    и тот же, а ``None`` в поле — это «карточки нет», а не «не проверяли».
    Мягко удалённые карточки не считаются: уволенный сотрудник не должен
    навсегда блокировать свою учётку от повторного заведения.
    """
    if not users:
        return users
    linked = dict(
        Employee.objects.filter(user_id__in=[row["id"] for row in users], is_deleted=False)
        .values_list("user_id", "id")
    )
    for row in users:
        row["employee_id"] = linked.get(row["id"])
    return users


def suggest_matches(*, email: str = "", phone: str = "", first_name: str = "",
                    last_name: str = "", patronymic: str = "",
                    exclude_employee_id: int | None = None,
                    limit: int = 5) -> dict:
    """Два ответа на «кажется, этого человека система уже знает».

    ``employees`` — карточка уже есть (заводить второй раз не надо);
    ``users`` — карточки нет, но есть учётка (вот откуда взять данные).
    Учётки, у которых карточка уже есть, помечены ``employee_id`` и НЕ
    выкидываются: «у Иванова уже есть карточка» — полезный ответ, молчание
    на его месте выглядит как «Иванова система не знает».
    """
    users = annotate_employee_links(users_interface.find_user_matches(
        email=email, phone=phone, first_name=first_name,
        last_name=last_name, patronymic=patronymic, limit=limit,
    ))

    return {
        "users": users,
        "employees": _employee_matches(
            email=email, phone=phone, first_name=first_name, last_name=last_name,
            exclude_employee_id=exclude_employee_id, limit=limit,
        ),
    }


# ── Массовый импорт ───────────────────────────────────────────────────────

def import_candidates(search: str | None = None, limit: int = 200) -> list[dict]:
    """Учётки, для которых карточки сотрудника ещё нет.

    Отсекаются по ДВУМ признакам: занятая ``user_id`` (карточка привязана
    явно) и совпадающий email (карточку завели раньше, чем появилась
    привязка, — исторически это основной способ, которым они находят друг
    друга: ``hr_access.resolve_hr_access`` ищет сотрудника
    ``Q(user_id=…) | Q(email=…)``). Без второго признака список предлагал бы
    импортировать людей, которые уже заведены.
    """
    users = users_interface.list_user_prefills(search=search, limit=limit)
    if not users:
        return []

    taken_user_ids = set(
        Employee.objects.filter(user_id__isnull=False).values_list("user_id", flat=True)
    )
    taken_emails = {
        value.strip().lower()
        for value in Employee.objects.filter(is_deleted=False).values_list("email", flat=True)
        if value
    }
    return [
        row for row in users
        if row["id"] not in taken_user_ids
        and (row["email"] or "").strip().lower() not in taken_emails
    ]


def bulk_import(*, user_ids: list[int], department_id: int, position_id: int,
                hire_date, status: str, changed_by_id: int) -> dict:
    """Завести карточки пачкой из выбранных учёток.

    Отдел, должность, дата приёма и статус — общие на всю пачку: это ровно
    те поля, которых учётка не знает, и спрашивать их по одному на каждого
    означало бы не массовый импорт, а ту же форму N раз.

    Каждая карточка создаётся в СВОЕЙ вложенной транзакции: один сбойный
    (занятый email, гонка за user_id) не должен откатывать остальных —
    иначе импорт сорока человек проваливается целиком из-за одного. Отчёт
    возвращает и созданных, и пропущенных с причиной.
    """
    employee_service._assert_department_exists(department_id)
    employee_service._assert_position_exists(position_id)

    created: list[Employee] = []
    skipped: list[dict] = []

    for user_id in dict.fromkeys(user_ids):
        data = users_interface.get_user_prefill(user_id)
        if data is None:
            skipped.append({"user_id": user_id, "reason": "user_not_found"})
            continue

        email = (data["email"] or "").strip()
        if not email:
            skipped.append({"user_id": user_id, "reason": "no_email"})
            continue
        if Employee.objects.filter(user_id=user_id).exists():
            skipped.append({"user_id": user_id, "reason": "already_linked"})
            continue
        if employee_service._email_taken(email):
            skipped.append({"user_id": user_id, "reason": "email_taken"})
            continue

        # Фамилия и имя обязательны в модели, а в учётке могут быть пустыми
        # (её заводят по одному email). Берём full_name, который у users уже
        # умеет откатываться на display_name/username — пустая карточка
        # бесполезнее карточки с неидеальным именем.
        first_name = (data["first_name"] or "").strip()
        last_name = (data["last_name"] or "").strip()
        if not first_name and not last_name:
            first_name = (data["full_name"] or email).strip()

        try:
            with transaction.atomic():
                employee = Employee.objects.create(
                    user_id=user_id,
                    first_name=first_name or "—",
                    last_name=last_name,
                    middle_name=_clean(data["patronymic"]),
                    email=email,
                    phone=_clean(data["phone"]),
                    department_id=department_id,
                    position_id=position_id,
                    hire_date=hire_date,
                    status=status,
                    avatar_url=_clean(data["avatar_url"]),
                    bio=_clean(data["bio"]),
                )
                audit_service.log(
                    entity_type="employee",
                    entity_id=employee.id,
                    action="create",
                    new_values={"_source": f"{SOURCE_USER}:{user_id}", "email": email},
                    changed_by=changed_by_id,
                )
        except Exception:  # noqa: BLE001 — сосед по пачке не виноват
            skipped.append({"user_id": user_id, "reason": "create_failed"})
            continue

        created.append(employee)

    return {"created": created, "skipped": skipped}


def resolve_matches_query(params: dict) -> dict:
    """Разбор query-строки ``GET /employees/match-suggestions``."""
    return {
        "email": (params.get("email") or "").strip(),
        "phone": (params.get("phone") or "").strip(),
        "first_name": (params.get("first_name") or "").strip(),
        "last_name": (params.get("last_name") or "").strip(),
        "patronymic": (params.get("patronymic") or "").strip(),
    }


__all__ = [
    "SOURCE_USER", "SOURCE_EMPLOYEE", "SOURCE_MAILBOX", "SOURCE_TYPES",
    "TRANSFERABLE_FIELDS", "TRANSFER_FIELDS",
    "STATE_FILL", "STATE_CONFLICT", "STATE_SAME",
    "SourceNotFound", "UnknownSourceType", "UserAlreadyLinked", "UserNotFound",
    "Prefill", "build_prefill", "diff", "preview", "link_user",
    "assert_user_available", "apply_prefill", "suggest_matches",
    "annotate_employee_links",
    "import_candidates", "bulk_import", "resolve_matches_query",
]
