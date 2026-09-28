"""Кто держит роль — для диалога удаления.

Роль удаляется только неиспользуемой, и отказ обязан называть ИМЕНА, а не
число: «роль назначена трём должностям» не говорит, к кому идти, и снять её
по такому отказу нельзя — придётся искать вручную по всем компаниям.

Держателей два вида, и различать их надо: должностной получил роль вместе с
должностью (снимать нужно у должности, иначе она вернётся следующему
сотруднику), личный — персональным назначением.

⚠️ Кадровые данные лежат в схемах компаний, поэтому обход идёт ПО КОМПАНИЯМ:
на каждую — вход в её схему и один запрос. Иначе ``search_path`` остался бы на
``public``, где этих таблиц нет, и список молча оказался бы пустым.
"""

from __future__ import annotations

from collections import defaultdict

from django.db import transaction

from apps.access.models import PositionRole, RoleAssignment, RolePermission
from apps.core.services import ServiceDisabled
from htqweb.fallback import fallback

POSITION = "position"
PERSONAL = "personal"


def _describe(user_id: int, company: str, source: str) -> dict:
    """Строка держателя: имя, компания, отдел, должность.

    Вызывается ВНУТРИ контекста компании — кадровая карточка иначе не найдётся.
    """
    from apps.hr import interface as hr
    from apps.users import interface as users

    brief = hr.get_employee_brief(user_id)
    if brief is None:
        # Человек без кадровой карточки: директор холдинга, подрядчик,
        # служебная учётка. Имя всё равно нужно — иначе в списке будет голый id.
        account = users.get_user_brief(user_id) or {}
        return {
            "user_id": user_id, "company": company, "source": source,
            "full_name": account.get("full_name") or account.get("username") or f"#{user_id}",
            "department": None, "position": None,
        }

    department = (hr.get_department_brief(brief["department_id"])
                  if brief.get("department_id") else None)
    return {
        "user_id": user_id, "company": company, "source": source,
        "full_name": brief["full_name"],
        "department": department["name"] if department else None,
        "position": brief.get("position_title"),
    }


def holders(role_id: int) -> list[dict]:
    """Все, у кого сейчас есть эта роль, по всем компаниям.

    Обе выборки идут БЕЗ фильтра по компании, и это не недосмотр: роль одна на
    всю группу, удалять её нельзя, пока она держится хоть где-то. Фильтр здесь
    сделал бы ответ ложным — держатели в соседней компании исчезли бы из
    списка, а роль выглядела бы свободной.
    """
    from htqweb.tenancy.db import use_company

    by_company_positions: dict[str, list[int]] = defaultdict(list)
    # cross-company: см. докстринг — фильтр по компании исказил бы ответ.
    for row in PositionRole.objects.filter(role_id=role_id):
        by_company_positions[row.company_slug].append(row.position_id)

    by_company_users: dict[str, list[int]] = defaultdict(list)
    # cross-company: та же причина.
    for row in RoleAssignment.objects.filter(role_id=role_id):
        by_company_users[row.company_slug].append(row.user_id)

    found: list[dict] = []
    for company in sorted(set(by_company_positions) | set(by_company_users)):
        try:
            with use_company(company):
                from apps.hr import interface as hr

                positions = by_company_positions.get(company, [])
                if positions:
                    for position_id, user_ids in hr.resolve_position_users(positions).items():
                        for user_id in user_ids:
                            found.append({**_describe(user_id, company, POSITION),
                                          "position_id": position_id})
                for user_id in by_company_users.get(company, []):
                    found.append({**_describe(user_id, company, PERSONAL),
                                  "position_id": None})
        except Exception as exc:
            # Компания из строки прав может не существовать физически (слаг с
            # опечаткой, снесённая схема). Это ПОДМЕНА — список окажется
            # неполным, — и молчать о ней нельзя: администратор решит, что роль
            # свободна, и удалит её.
            fallback("access.holders.company_unavailable", None,
                     reason="схема компании недоступна, держатели не перечислены",
                     exc=exc, expected=True, company=company, role_id=role_id)

    return sorted(found, key=lambda row: (row["company"], row["full_name"]))


def _serving_holder_rows(company: str) -> list[tuple[int, dict]]:
    """Обход предков → пары ``(user_id, витринная запись)`` — ядро задачи 7
    (``external_holders``) и задачи 8 блока C (``serving_holder_ids``).

    Обход — зеркало ``inheritance.ancestors_of``, и по той же причине: вопрос
    здесь тот же, что решает ``inheritance.inherit`` для одного пользователя
    («кто НАДО МНОЙ даёт права здесь»), только сразу для ВСЕХ, кто фактически
    что-то держит, а не для одного. Видимость итогового списка
    (``Company.show_external_holders``, решение заказчика 4) — забота
    ``apps.companies`` и её HTTP-гейта; эта функция безусловно отвечает на
    вопрос «кто держит права» и о настройке видимости не знает вовсе —
    вызывающий обязан спросить её САМ, до вызова.

    Для каждого действующего предка: его должности с назначенной ролью
    (``PositionRole``, тот же приём, что в ``holders()`` выше — фильтр по
    ОДНОЙ компании на итерацию, а не общий обход) сужаются до обслуживающих
    (``hr.get_positions_brief`` — задача 7 добавила туда флаг аддитивно, тем
    же приёмом, что раньше в ``get_employee_brief``), и по ним резолвятся
    действующие держатели учёток (``hr.resolve_position_users``, тот же
    приём, что и в ``holders()``). Должность без единой роли (пустой
    ``PositionRole``) кандидатов не даёт вовсе — как и в ``inheritance.inherit``,
    признак сам по себе не право, а лишь канал для ролей должности.

    Уровни модулей на кандидата считаются ТЕМ ЖЕ путём, что у любого обычного
    запроса — ``resolve.permissions_for`` внутри контекста ``company``, — а не
    отдельной проекцией ``RolePermission`` → уровень: так список не может
    разойтись с тем, что кандидат реально увидит на своём ``/me``, зайдя в
    ``company``. Кандидат без единого уровня (роль назначена, но её
    ``RolePermission`` не открывает ни одного модуля) в список не попадает —
    он ничего не «держит», только числится, и его отсутствие здесь означает,
    что ни ``external_holders``, ни ``serving_holder_ids`` (задача 8: кому
    заводить ``CompanyMembership``) о нём не узнают — семантика «держит
    права» ОДНА на обоих потребителей, а не расходится между витриной и
    командой, которая по этому же признаку заводит членство.

    Цена этого повторного использования: ``resolve.permissions_for`` сам
    заново обходит всю цепочку предков на КАЖДОГО кандидата, то есть общая
    стоимость — O(предков × кандидатов × предков), а не O(предков ×
    кандидатов). При нынешнем размере дерева компаний это приемлемо; если
    дерево вырастет настолько, что это станет заметно, здесь есть что
    оптимизировать (например, посчитать уровни один раз на company и
    переиспользовать на всех кандидатов).
    """
    from types import SimpleNamespace

    from apps.access.services import inheritance, resolve
    from apps.companies import interface as companies
    from apps.hr import interface as hr
    from htqweb.tenancy.db import use_company

    rows: list[tuple[int, dict]] = []
    seen_users: set[int] = set()
    for ancestor in inheritance.ancestors_of(company):
        row = companies.get_company(ancestor)
        if row is None or not row.get("is_active"):
            continue

        position_ids = list(
            PositionRole.objects.filter(company_slug=ancestor)
            .values_list("position_id", flat=True).distinct()
        )
        if not position_ids:
            continue

        try:
            # Собственный savepoint (зеркало inheritance.inherit, см. её
            # докстринг) — ошибка внутри НЕ должна портить транзакцию
            # вызывающего: без него пойманное ниже исключение оставило бы
            # внешнюю транзакцию (если эта функция вызвана внутри чужого
            # atomic()) в состоянии отказа, и самый первый следующий запрос
            # вызывающего упал бы посторонней ошибкой вместо того, чтобы
            # просто не увидеть держателей от одного предка.
            with transaction.atomic():
                with use_company(ancestor):
                    serving_ids = [p["id"] for p in hr.get_positions_brief(position_ids)
                                  if p["serves_subsidiaries"]]
                    if not serving_ids:
                        continue
                    users_by_position = hr.resolve_position_users(serving_ids)
                    candidates = sorted(
                        {uid for uids in users_by_position.values() for uid in uids}
                        - seen_users
                    )
                    descriptions = {uid: _describe(uid, ancestor, POSITION) for uid in candidates}
        except ServiceDisabled as exc:
            # Штатная деградация: hr выключен целиком у предка. Та же ветка,
            # что и в inheritance.inherit — тихо, уровнем INFO.
            fallback("access.holders.hr_unavailable", None,
                     reason="кадровый модуль недоступен у предка, внешние "
                            "держатели не перечислены", exc=exc, expected=True,
                     company=ancestor)
            continue
        except Exception as exc:
            # НЕ hr-рубильник — похоже на порчу данных реестра компаний
            # (осиротевшая строка после неудачного отката company_create,
            # см. CLAUDE.md). Должно быть слышно, а не маскироваться под
            # «hr выключен».
            fallback("access.holders.ancestor_schema_unavailable", None,
                     reason="схема компании-предка недоступна, внешние "
                            "держатели не перечислены", exc=exc, expected=False,
                     company=ancestor)
            continue

        for user_id, description in descriptions.items():
            with use_company(company):
                levels = resolve.permissions_for(
                    SimpleNamespace(id=user_id, is_superuser=False), company,
                )
            if not levels:
                continue
            seen_users.add(user_id)
            rows.append((user_id, {
                "full_name": description["full_name"],
                "home_company": row["name"],
                "position": description["position"],
                "modules": [{"module": module, "level": info["level"]}
                           for module, info in sorted(levels.items())],
            }))

    return rows


def external_holders(company: str) -> list[dict]:
    """Кто из компаний-предков сейчас держит права В ``company`` благодаря
    обслуживающей должности — задача 7 блока C. Витрина над
    ``_serving_holder_rows`` (см. её докстринг для полной механики обхода)."""
    return sorted(
        (record for _user_id, record in _serving_holder_rows(company)),
        key=lambda row: (row["home_company"], row["full_name"]),
    )


def serving_holder_ids(company: str) -> list[int]:
    """Id держателей обслуживающих должностей предков, реально несущих права
    в ``company`` — задача 8 блока C.

    То же ядро, что ``external_holders`` выше, без витринного оформления:
    используется, чтобы завести им ``CompanyMembership``
    (``manage.py company_grant --serving``), посчитать разрыв при заведении
    компании (``company_create``) и в метрике
    ``apps.access.metrics``. Три места читают ОДИН и тот же список, а не три
    независимых определения «кто держит права через обслуживающую должность».
    """
    return sorted({user_id for user_id, _record in _serving_holder_rows(company)})


# ── Держатели признака на узле — получатели уведомлений (БЗО, этап 2 A) ──


def _granting_role_ids(node: str, flag: str) -> set[int]:
    """Роли, у которых на ``node`` действует ``flag``.

    Действующая глубина роли на узле — строка ближайшего предка, у которого
    она задана (``resolve._nearest``, то же правило, что у ``flags_for``);
    пустая строка — запрет, а не «ищи выше». Роли одного пользователя
    складываются объединением, поэтому пользователь несёт признак ровно
    тогда, когда его несёт хоть одна его роль, — и обратный поиск можно
    вести от ролей, а не перебирать людей.
    """
    from apps.access import registry
    from apps.access.services.resolve import _nearest

    by_role: dict[int, dict[str, frozenset[str]]] = defaultdict(dict)
    for row in RolePermission.objects.filter(node__in=registry.self_and_ancestors(node)):
        by_role[row.role_id][row.node] = row.flags
    return {role_id for role_id, nodes in by_role.items() if flag in _nearest(nodes, node)}


def _position_holder_ids(company: str, position_ids: list[int], *,
                         serving_only: bool) -> set[int]:
    """Действующие держатели должностей ``company`` с активной учёткой
    (``hr.resolve_position_users`` — то же определение, по которому маршруты
    согласования ищут исполнителя должности, включая временных исполнителей
    D-22). ``serving_only`` — только должности, обслуживающие дочерние
    компании (наследование блока C).

    Своя точка сохранения и та же развилка отказов, что у
    ``_serving_holder_rows``: выключенный ``hr`` — штатная деградация,
    недоступная схема — порча реестра, и она должна быть слышна.
    """
    from apps.hr import interface as hr
    from htqweb.tenancy.db import use_company

    if not position_ids:
        return set()
    try:
        with transaction.atomic():
            with use_company(company):
                ids = list(position_ids)
                if serving_only:
                    ids = [p["id"] for p in hr.get_positions_brief(ids)
                           if p["serves_subsidiaries"]]
                    if not ids:
                        return set()
                return {user_id for user_ids in hr.resolve_position_users(ids).values()
                        for user_id in user_ids}
    except ServiceDisabled as exc:
        fallback("access.holders.node_hr_unavailable", None,
                 reason="кадровый модуль недоступен, держатели должностей не учтены",
                 exc=exc, expected=True, company=company)
    except Exception as exc:
        fallback("access.holders.node_schema_unavailable", None,
                 reason="схема компании недоступна, держатели должностей не учтены",
                 exc=exc, expected=False, company=company)
    return set()


def node_holder_ids(node: str, flag: str, company: str) -> list[int]:
    """Кто в ``company`` несёт ``flag`` на ``node`` — по возрастанию id.

    Обратная сторона ``resolve.flags_for``: роли с действующим признаком
    (с наследованием глубины от предка узла) → их держатели тремя путями,
    как их складывает ``resolve._role_scopes``:

    - личные назначения ``RoleAssignment`` в компании;
    - должности компании (``PositionRole``) → их держатели;
    - обслуживающие должности действующих компаний-предков
      (``inheritance.inherit``) → их держатели.

    Итог сужается до участников компании с действующей учёткой
    (``companies.active_member_ids``): назначения переживают отзыв членства
    (CLAUDE.md, «Модель прав — одна»), а уведомлять того, кто не может
    войти в компанию, незачем. Суперпользователь ролей не требует и сюда не
    попадает, если сам их не держит: список — о ролях, а не о тех, кому
    открыто всё.

    Отличие от прямого пути: держатель должности ищется так, как его ищут
    маршруты согласования (действующий сотрудник, привязанный к учётке, и
    временный исполнитель должности), а не по карточке одного пользователя.
    """
    from apps.access.services import inheritance
    from apps.companies import interface as companies

    roles = _granting_role_ids(node, flag)
    if not roles:
        return []

    found = set(RoleAssignment.objects.filter(company_slug=company, role_id__in=roles)
                .values_list("user_id", flat=True))
    own_positions = list(PositionRole.objects.filter(company_slug=company, role_id__in=roles)
                         .values_list("position_id", flat=True).distinct())
    found |= _position_holder_ids(company, own_positions, serving_only=False)

    for ancestor in inheritance.ancestors_of(company):
        row = companies.get_company(ancestor)
        if row is None or not row.get("is_active"):
            continue  # архивный предок ролей не даёт, но обход идёт выше
        positions = list(PositionRole.objects.filter(company_slug=ancestor, role_id__in=roles)
                         .values_list("position_id", flat=True).distinct())
        found |= _position_holder_ids(ancestor, positions, serving_only=True)

    if not found:
        return []
    return sorted(found & set(companies.active_member_ids(company)))
