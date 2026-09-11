"""Выдача прав пользователям на работу в компании (``CompanyMembership``).

Общая точка для ``manage.py tenancy_bootstrap`` (флаг ``--grant-all``) и
``manage.py company_grant``: обе команды заводят строки ``CompanyMembership``,
и обеим нужна одна и та же идемпотентность — повторный запуск не должен
падать ``IntegrityError`` на уникальном индексе ``uniq_membership`` и не
должен плодить дублирующиеся строки, а должен тихо сообщить "уже есть".

Список активных пользователей читается через ``apps.users.interface``, а не
прямым импортом ``apps.users.models`` (запрещён ``apps/core/tests/
test_app_isolation.py``). Подходящей "дай всех активных" функции в интерфейсе
нет — ``list_users_brief`` создавалась как источник для пикеров (HR, поиск
messenger'а) и по умолчанию режет выдачу ``limit``'ом. Здесь это тот же самый
метод, вызванный с заведомо большим лимитом: он уже считает ``is_active`` по
``UserStatus`` за нас (см. его докстринг — "callers that need active-only
filter on the returned is_active themselves"), и заводить второй способ
сравнения со статусом пользователя в этой аппке означало бы протащить сюда
знание об enum'е ``apps.users.models.UserStatus``, которого у ``companies``
не должно быть вовсе.
"""

from __future__ import annotations

from apps.users.interface import get_user_brief, list_users_brief

from ..models import Company, CompanyMembership

# "Все" активные пользователи платформы для --grant-all: bootstrap разово
# сводит всю текущую базу в одну компанию, значит верхняя граница — реальное
# число заведённых пользователей, а не число пользователей одного пикера.
_ALL_USERS_LIMIT = 1_000_000


def active_user_ids() -> list[int]:
    """Id всех пользователей платформы со статусом "активен"."""
    return [row["id"] for row in list_users_brief(limit=_ALL_USERS_LIMIT)
            if row["is_active"]]


def find_user_id(identifier: str) -> int | None:
    """Резолв ``--user <id|username>`` в id, или ``None`` если не нашли.

    Числовой ``identifier`` — это id, берётся напрямую (после проверки, что
    такой пользователь существует). Иначе — username, точное совпадение без
    учёта регистра (``list_users_brief`` ищет по подстроке, поэтому нужно
    вручную отобрать строку с точным совпадением, а не первую же похожую).
    """
    if identifier.isdigit():
        row = get_user_brief(int(identifier))
        return row["id"] if row else None

    needle = identifier.strip().lower()
    for row in list_users_brief(search=identifier, limit=50):
        if row["username"].lower() == needle:
            return row["id"]
    return None


def grant_membership(company: Company, user_id: int, *,
                      is_default: bool = False) -> bool:
    """Выдать пользователю право работать в компании.

    Идемпотентно: повторный вызов с теми же (company, user_id) не создаёт
    вторую строку — ``get_or_create`` по тому же ключу, что несёт
    ``uniq_membership``. Возвращает ``True``, если строка создана заново,
    ``False`` — если членство уже было.
    """
    _, created = CompanyMembership.objects.get_or_create(
        company=company, user_id=user_id,
        defaults={"is_default": is_default},
    )
    return created
