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

from apps.access.models import PositionRole, RoleAssignment
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
