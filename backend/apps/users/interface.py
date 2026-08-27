"""Публичный API аппки users для ДРУГИХ аппок.

Единственный способ, которым сосед имеет право обращаться к users. Прямой
импорт apps.users.models / apps.users.services из другой аппки запрещён и
ловится тестом apps/core/tests/test_app_isolation.py.

Каждая функция начинается с require_service("users"): если аппка выключена,
вызывающий получит ServiceDisabled, который api_view превратит в 503-конверт
(а не в 500) — см. htqweb/http.py. Это тот же контракт, что и у
apps.cms.interface — см. его докстринг для полного объяснения.

Возвращаются только простые dict'ы, никогда ORM-объекты User — сосед не
должен получить возможность мутировать чужую модель напрямую, а форма
{id, username, email, full_name, is_active} — минимальный "brief"-профиль,
которого достаточно для чужих UI-списков (участник задачи, автор события и
т.п.), без полного профиля (аватар, роли, settings — см.
apps.users.services.profile_service.build_response, который остаётся
приватным для этой аппки).

full_name — это apps.users.services.options_service.full_name_for
("{first_name} {last_name}".strip(), с откатом на display_name, затем
username), вызывается отсюда напрямую, а не копируется. ЭТО НЕ то же самое,
что profile_service.build_response's fio: у fio другой порядок полей
("{last_name} {first_name} {patronymic}"), в нём участвует patronymic и
нет отката на display_name/username. Не путать одно с другим.

Запросы здесь сужены до колонок, которые реально нужны (.values(...)) —
это граница между аппками, и незачем поднимать в память password_hash и
settings из полной User-строки ради 5 полей брифа.

``list_users_brief``/``create_user`` — вторая пара функций (задача Р3, без
S2S): подключают давно отложенных потребителей hr (`/employees/users/`,
пикер «создать сотрудника из пользователя») и messenger (`/users/search`).
``list_users_brief`` НЕ фильтрует по статусу — HR-исходник
(``services/hr/app/api/v1/employees.py::list_user_options``) проксировал
`user-service GET admin/users/`, который отдаёт ВСЕХ пользователей без
фильтра; messenger-исходник, наоборот, фильтровал ``is_active=True`` —
поскольку эти два потребителя расходятся именно в фильтрации, а не в форме
данных, фильтрацию по активности несёт вызывающая сторона (каждая строка уже
содержит ``is_active``), а не эта функция. ``create_user`` не дублирует
``admin_service.create_user`` — она ПЕРЕИСПОЛЬЗУЕТ её (username выводится из
email, временный пароль генерируется здесь же, как в HR-исходнике
``create_user_option``), и заворачивает её ``DuplicateEmail``/
``DuplicateUsername`` в одноимённые исключения ЭТОГО модуля — сосед не имеет
права ловить исключения из ``apps.users.services.admin_service`` напрямую
(test_app_isolation.py запрещает даже импорт), только из ``apps.users.
interface``.

``get_user_prefill``/``list_user_prefills``/``find_user_matches`` — третья
группа: учётка как ИСТОЧНИК ДАННЫХ для карточки сотрудника (apps.hr), а не
как пункт списка. Отдельная форма ответа, шире брифа ровно на те колонки,
которые есть и в ``Employee``; подробности — в комментарии над ними.
"""
from __future__ import annotations

import secrets
from types import SimpleNamespace
from typing import Iterable

from django.db.models import Q

from htqweb import phone as phone_utils

from apps.core.services import require_service
from apps.users.models import User, UserStatus
from apps.users.services import admin_service
from apps.users.services.options_service import full_name_for

_BRIEF_FIELDS = ("id", "username", "email", "first_name", "last_name",
                 "display_name", "status")


class DuplicateEmail(Exception):
    """``create_user``: email already belongs to another user. Callers map
    this to 409 (see ``apps.hr.views``)."""


class DuplicateUsername(Exception):
    """``create_user``: the username derived from ``email`` collided with an
    existing user. Callers map this to 409 (see ``apps.hr.views``)."""


def _brief_from_values(row: dict) -> dict:
    # full_name_for only reads .first_name/.last_name/.display_name/.username —
    # a SimpleNamespace satisfies that without instantiating a real User row
    # (this module never hands out ORM objects, not even internally).
    stub = SimpleNamespace(first_name=row["first_name"], last_name=row["last_name"],
                          display_name=row["display_name"], username=row["username"])
    return {
        "id": row["id"],
        "username": row["username"],
        "email": row["email"],
        "full_name": full_name_for(stub),
        "is_active": row["status"] == UserStatus.ACTIVE,
    }


def _option_from_user(user) -> dict:
    """Shared dict-builder for ``list_users_brief``/``create_user`` — a wider
    "option" shape than ``_brief_from_values`` (adds ``first_name``/
    ``last_name`` separately, needed by HR's create-employee-from-user form
    prefill). Accepts anything with the right attributes — a real ``User``
    row (``create_user``) or a ``SimpleNamespace`` built from ``.values()``
    (``list_users_brief``), same trick as ``_brief_from_values``."""
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "full_name": full_name_for(user),
        "is_active": user.status == UserStatus.ACTIVE,
    }


def _option_from_values(row: dict) -> dict:
    stub = SimpleNamespace(id=row["id"], username=row["username"], email=row["email"],
                          first_name=row["first_name"], last_name=row["last_name"],
                          display_name=row["display_name"], status=row["status"])
    return _option_from_user(stub)


def _derive_username(email: str) -> str:
    """Port of ``create_user_option``'s username derivation: the email's
    local part, stripped down to alnum/``.``/``_``/``-``, truncated to the
    ``User.username`` column's practical length. Collisions aren't guessed
    around here — they surface as ``DuplicateUsername``, same as the
    source's "collisions are surfaced by the upstream service" comment."""
    local = (email.split("@", 1)[0] if email else "") or "user"
    username = "".join(ch for ch in local if ch.isalnum() or ch in {".", "_", "-"})[:32]
    return username or "user"


def get_user_brief(user_id: int) -> dict | None:
    """Minimal profile for a single user, or ``None`` if ``user_id`` doesn't
    resolve to any row (unknown/deleted user)."""
    require_service("users")
    row = User.objects.filter(pk=user_id).values(*_BRIEF_FIELDS).first()
    return _brief_from_values(row) if row is not None else None


def find_user_ids_by_emails(emails: Iterable[str]) -> dict[str, int]:
    """``{адрес в нижнем регистре: user_id}`` для тех адресов, под которыми в
    платформе есть пользователь.

    Пакетно, а не по одному: единственный потребитель — сверка почтовых
    ящиков (``apps.mail.services.reconcile_service``), которая проверяет
    десятки адресов за прогон, и запрос на каждый превратил бы её в N+1.

    Регистр приводится так же, как при создании пользователя
    (``admin_service``: ``email.strip().lower()``), иначе ящик
    ``Sanzhar@htq.group`` не нашёл бы владельца с ``sanzhar@htq.group``.
    Адреса без пользователя в ответ просто не попадают.
    """
    require_service("users")
    normalized = {value.strip().lower() for value in emails if value and value.strip()}
    if not normalized:
        return {}
    rows = (User.objects
            .filter(email__in=normalized)
            .values_list("email", "id"))
    return {email.strip().lower(): user_id for email, user_id in rows}


def verify_password(user_id: int, password: str) -> bool:
    """Re-check one user's own password — a *step-up* confirmation, not a
    login: it issues no token, touches no ``last_login``, and returns a plain
    bool instead of a User.

    The one caller today is ``apps.core.infrastructure``'s "reveal
    infrastructure credentials" flow, which makes the admin re-enter their
    password before plaintext secrets are unmasked. Before the cutover that
    check was an HTTP round-trip from admin-service to user-service
    (``POST /api/users/v1/token/`` with the admin's own email); in the
    monolith there is no network hop, and neighbours may not import
    ``apps.users.services`` directly (apps/core/tests/test_app_isolation.py),
    so the check belongs here.

    Deliberately narrower than ``auth_service.authenticate``: the caller
    already holds a validated JWT and only needs "does this password still
    belong to *this* user id". Non-active accounts and unknown ids answer
    ``False`` rather than raising — a step-up prompt has exactly two useful
    outcomes, and distinguishing "no such user" from "wrong password" here
    would leak account state to whoever is at the keyboard.
    """
    require_service("users")
    user = User.objects.filter(pk=user_id, status=UserStatus.ACTIVE).first()
    if user is None:
        return False
    return user.check_password(password)


def get_users_brief(user_ids: Iterable[int]) -> list[dict]:
    """Bulk variant of ``get_user_brief`` — one query for every id in
    ``user_ids``. Unknown ids are simply absent from the result (same
    "unknown -> not present" contract as ``get_user_brief``'s ``None``,
    just expressed as omission instead of a null entry since this returns
    a list)."""
    require_service("users")
    rows = User.objects.filter(pk__in=list(user_ids)).values(*_BRIEF_FIELDS)
    return [_brief_from_values(row) for row in rows]


def list_users_brief(search: str | None = None, limit: int = 100) -> list[dict]:
    """Users as picker options — ``{id, username, email, first_name,
    last_name, full_name, is_active}`` — for hr's ``/employees/users/`` GET
    and messenger's ``/users/search``.

    No status filter is applied here (see the module docstring for why);
    callers that need active-only (messenger) filter on the returned
    ``is_active`` themselves. ``search`` — case-insensitive OR-match across
    ``username``/``first_name``/``last_name``/``email`` (the same four
    columns messenger's original ``search_users`` ORed over
    ``ChatUserReplica``), falsy/``None`` returns everyone up to ``limit``.
    Ordered by ``last_name``, ``first_name`` — a deterministic, alphabetical
    order reasonable for either consumer (neither original ordering, HR's
    ``-date_joined`` admin-list default or messenger's identical
    last_name/first_name, is authoritative for this shared primitive)."""
    require_service("users")
    qs = User.objects.all()
    if search:
        qs = qs.filter(
            Q(username__icontains=search)
            | Q(first_name__icontains=search)
            | Q(last_name__icontains=search)
            | Q(email__icontains=search)
        )
    rows = qs.order_by("last_name", "first_name").values(*_BRIEF_FIELDS)[:limit]
    return [_option_from_values(row) for row in rows]


def create_user(*, email: str, first_name: str = "", last_name: str = "",
                patronymic: str = "", must_change_password: bool = True) -> dict:
    """Create a platform user from a neighbour app — hr's "create employee
    from a brand-new user" dialog (``HRUserCreateRequest``).

    Reuses ``apps.users.services.admin_service.create_user`` for the actual
    creation (uniqueness checks, ``set_password``, ``must_change_password``)
    rather than duplicating it — this function only adds the bit the
    source's ``create_user_option`` did locally before calling user-service:
    deriving ``username`` from the email local-part and minting a random
    temp password. Raises this module's own ``DuplicateEmail``/
    ``DuplicateUsername`` (never ``admin_service``'s — neighbours may not
    import ``apps.users.services``, only this module) so the caller can map
    them to 409 without knowing admin_service exists.

    **Пароль генерируется ЗДЕСЬ и не принимается аргументом.** Обсуждалась и
    обратная развязка — пусть HR задаёт пароль руками и сам передаёт его
    сотруднику, — но она требует, чтобы пароль прошёл через форму, сеть и
    глаза заводящего, а гарантия «первый вход заканчивается сменой» держалась
    бы на клиенте. Здесь секрет не покидает сервер иначе как одним полем
    ответа на создание, и подделать его вызывающему нечем.

    **``generated_password`` в ответе — единственный раз, когда этот модуль
    отдаёт секрет, и это исправление, а не послабление.** Раньше временный
    пароль генерировался «для себя» и не показывался никому: HR заводил
    сотрудника, сотрудник не мог войти, а узнать пароль было неоткуда —
    оставался только сброс через ``/admin/users``. Флаг
    ``must_change_password`` эту дыру не закрывает: он срабатывает ПОСЛЕ
    входа, а входа-то и не было.

    Пароль возвращается ТОЛЬКО отсюда и ТОЛЬКО при создании — ни
    ``get_user_prefill``, ни ``list_user_prefills``, ни ``list_users_brief``
    его не несут и нести не могут (у них другой построитель словаря). Тот
    же приём уже применён к почтовым ящикам: ``mailbox_service`` отдаёт
    ``generated_password`` в ответе на создание и нигде больше.

    Вызывающий обязан показать пароль человеку сразу — второго шанса нет,
    в базе лежит только хеш."""
    require_service("users")
    email_norm = (email or "").strip().lower()
    username = _derive_username(email_norm)
    display_name = f"{first_name} {last_name}".strip() or username
    password = secrets.token_urlsafe(12)

    try:
        user = admin_service.create_user(
            username=username,
            email=email_norm,
            password=password,
            first_name=first_name,
            last_name=last_name,
            patronymic=patronymic,
            display_name=display_name,
            must_change_password=must_change_password,
        )
    except admin_service.DuplicateEmail:
        raise DuplicateEmail() from None
    except admin_service.DuplicateUsername:
        raise DuplicateUsername() from None

    # Сотрудника заводят по его рабочему адресу — если корпоративный ящик с
    # этим адресом уже существует, подключаем его сразу. Ящик НЕ создаётся:
    # HR-форма его не заказывала. Вызов ничего не бросает и ничего не значит,
    # когда подключать нечего (личная почта, ящика нет, занят другим).
    from apps.mail import interface as mail_interface

    mail_interface.attach_mailbox_by_email(user_id=user.id, email=email_norm)

    # Отдельным ключом, а не полем option-формы: ``_option_from_user`` строит
    # и строки СПИСКА тоже, и пароль в них попасть не должен ни при какой
    # правке этой функции.
    return {**_option_from_user(user), "generated_password": password}


# ── Префилл карточки сотрудника ───────────────────────────────────────────
#
# Третья группа функций (задача «подтянуть уже имеющиеся данные из
# Пользователей в Сотрудников»). Отличие от ``list_users_brief``/
# ``_option_from_user`` — не в наборе потребителей, а в НАЗНАЧЕНИИ формы:
# brief/option описывают пользователя как ПУНКТ СПИСКА (кого выбрать), а
# prefill — как ИСТОЧНИК ДАННЫХ (что перенести в чужую карточку). Поэтому
# сюда добавлены ровно те колонки, которые есть и у сотрудника
# (``patronymic``→``middle_name``, ``phone``, ``avatar_url``, ``bio``), и ни
# одной сверх: settings/roles/пароль к переносу отношения не имеют.
#
# Расширять brief-форму вместо новой было нельзя: её потребители (messenger,
# tasks, approvals, signoff) рисуют имя в списке, и таскать ради них био с
# телефоном каждого участника чата — лишние данные на границе аппок.

_PREFILL_FIELDS = ("id", "username", "email", "first_name", "last_name",
                   "patronymic", "phone", "avatar_url", "bio",
                   "display_name", "status")


def _prefill_from_values(row: dict) -> dict:
    stub = SimpleNamespace(first_name=row["first_name"], last_name=row["last_name"],
                           display_name=row["display_name"], username=row["username"])
    return {
        "id": row["id"],
        "username": row["username"],
        "email": row["email"],
        "full_name": full_name_for(stub),
        "first_name": row["first_name"],
        "last_name": row["last_name"],
        "patronymic": row["patronymic"],
        "phone": row["phone"],
        "avatar_url": row["avatar_url"],
        "bio": row["bio"],
        "is_active": row["status"] == UserStatus.ACTIVE,
    }


def get_user_prefill(user_id: int) -> dict | None:
    """Данные учётки как источник для чужой карточки, либо ``None``.

    Форма — ``{id, username, email, full_name, first_name, last_name,
    patronymic, phone, avatar_url, bio, is_active}``. Потребитель —
    ``apps.hr.services.employee_prefill_service``.
    """
    require_service("users")
    row = User.objects.filter(pk=user_id).values(*_PREFILL_FIELDS).first()
    return _prefill_from_values(row) if row is not None else None


def list_user_prefills(search: str | None = None, limit: int = 100) -> list[dict]:
    """``get_user_prefill`` для списка — пикер источника в HR-форме.

    Поиск и порядок — те же, что у ``list_users_brief`` (icontains OR по
    username/first_name/last_name/email, сортировка по фамилии): пикер
    сотрудника и пикер участника чата ищут людей одинаково, расходится только
    форма ответа. Статус так же НЕ фильтруется — HR должен видеть и
    неактивные учётки (каждая строка несёт ``is_active``), иначе завести
    карточку человеку, чей аккаунт ещё не подтверждён, будет нечем.
    """
    require_service("users")
    qs = User.objects.all()
    if search:
        qs = qs.filter(
            Q(username__icontains=search)
            | Q(first_name__icontains=search)
            | Q(last_name__icontains=search)
            | Q(email__icontains=search)
        )
    rows = qs.order_by("last_name", "first_name").values(*_PREFILL_FIELDS)[:limit]
    return [_prefill_from_values(row) for row in rows]


def find_user_matches(*, email: str = "", phone: str = "", first_name: str = "",
                      last_name: str = "", patronymic: str = "",
                      limit: int = 5) -> list[dict]:
    """Кандидаты «похоже, это тот же человек» по частично заполненной форме.

    Отвечает на вопрос HR-формы «а нет ли уже учётки у того, кого я сейчас
    завожу». Это НЕ поиск (``list_user_prefills``): там человек ищет осознанно
    и вводит запрос, здесь система сама сверяет уже набранное в полях и
    предлагает совпадение.

    Каждая строка — обычный prefill плюс два поля:

    * ``match_on`` — по чему совпало (``email``/``phone``/``full_name``/
      ``patronymic``): без него подсказка «похоже, это Иванов» выглядит
      гаданием, а с ним видно основание;
    * ``match_kind`` — ``exact`` (email или телефон: совпал идентификатор)
      либо ``similar`` (ФИО: однофамильцы реальны, и выдавать это за точное
      попадание нельзя).

    Порядок — от надёжного основания к слабому: email, телефон, ФИО. Пустые
    аргументы просто не участвуют; всё пустое → пустой ответ (а НЕ «все
    пользователи»: подсказка на пустой форме — это выгрузка справочника).
    """
    require_service("users")

    email_norm = (email or "").strip().lower()
    phone_tail = phone_utils.comparable_tail(phone)
    first = (first_name or "").strip()
    last = (last_name or "").strip()
    middle = (patronymic or "").strip()

    probes: list[tuple[str, str, object]] = []
    if email_norm:
        probes.append(("email", "exact", User.objects.filter(email__iexact=email_norm)))
    if phone_tail:
        probes.append((
            "phone", "exact",
            User.objects.exclude(phone="")
            .annotate(_phone_digits=phone_utils.digits_expr())
            .filter(_phone_digits__endswith=phone_tail),
        ))
    if first and last:
        probes.append((
            "full_name", "similar",
            User.objects.filter(first_name__iexact=first, last_name__iexact=last),
        ))

    if not probes:
        return []

    found: dict[int, dict] = {}
    order: list[int] = []
    for reason, kind, qs in probes:
        # Кап на КАЖДУЮ пробу, а не только на итог: однофамильцев может быть
        # больше, чем limit, и вытаскивать их всех ради пяти строк незачем.
        for row in qs.order_by("last_name", "first_name").values(*_PREFILL_FIELDS)[:limit]:
            entry = found.get(row["id"])
            if entry is None:
                entry = {**_prefill_from_values(row), "match_on": [], "match_kind": kind}
                found[row["id"]] = entry
                order.append(row["id"])
                # Отчество — не отдельная проба (само по себе оно никого не
                # опознаёт), но если совпало и оно, основание сильнее, и
                # подсказка вправе это показать.
                if middle and row["patronymic"] \
                        and row["patronymic"].strip().lower() == middle.lower():
                    entry["match_on"].append("patronymic")
            if reason not in entry["match_on"]:
                entry["match_on"].append(reason)
            if kind == "exact":
                entry["match_kind"] = "exact"

    return [found[user_id] for user_id in order[:limit]]
