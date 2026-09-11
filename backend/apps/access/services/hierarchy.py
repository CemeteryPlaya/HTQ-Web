"""Внешняя иерархия должностей — спека стадии 2, §1.4.

Дерево подчинения между компаниями НЕ хранится: оно выводится из дерева
владения (``companies.Company.parent``). Две таблицы с ответом на вопрос «кто
чей начальник» разъехались бы на первой же реорганизации, причём молча.

Иерархия задаёт подчинение и область, а не наследование прав: начальник из
вышестоящей компании не получает прав нижестоящей автоматически — он получает
их ролями своей должности, а иерархия лишь расширяет множество компаний, в
которых эти права действуют. Стадия 2 это множество вычисляет и отдаёт, но
выборки по нему не режет (спека §7).
"""

from __future__ import annotations

from apps.access.services.identity import identity
from htqweb.fallback import fallback


def companies_below(company: str) -> list[str]:
    """Слаги компаний ниже ``company`` по дереву владения, по алфавиту.

    Обход идёт снизу вверх от каждой компании и ограничен уже пройденными
    узлами: цикл, заведённый в обход приложения (``PROTECT`` на self-FK его не
    исключает), не должен вешать разрешение прав — оно выполняется на каждом
    запросе с гейтом.
    """
    from apps.companies import interface as companies

    parents: dict[str, str | None] = {}
    for slug in companies.active_company_slugs():
        row = companies.get_company(slug)
        parents[slug] = row.get("parent_slug") if row else None

    below: list[str] = []
    for slug in parents:
        if slug == company:
            continue
        seen = {slug}
        cursor = parents.get(slug)
        while cursor is not None and cursor not in seen:
            if cursor == company:
                below.append(slug)
                break
            seen.add(cursor)
            cursor = parents.get(cursor)
    return sorted(below)


def _is_external_manager(user_id: int) -> bool:
    """Руководящая ли должность у пользователя и включена ли внешняя иерархия.

    Поля ``is_manager`` и ``external_hierarchy`` заводит переработка HR (спека
    §1.6). До их появления ответ всегда ``False`` — и это корректное состояние
    «ни одна должность пока не помечена руководящей», а не сбой: интерфейс
    обязан показать пустую внешнюю иерархию, а не ошибку загрузки.
    """
    try:
        from apps.hr import interface as hr

        brief = hr.get_employee_brief(user_id)
    except Exception as exc:
        fallback("access.hierarchy.hr_unavailable", None,
                 reason="кадровый модуль недоступен, руководителя не определить",
                 exc=exc, expected=True, user_id=user_id)
        return False
    if brief is None:
        return False
    return bool(brief.get("is_manager")) and brief.get("external_hierarchy") == "inherit"


def subordinate_companies(user, company: str | None) -> list[str]:
    """Компании, над сотрудниками которых пользователь начальник по §1.4."""
    user_id, _ = identity(user)
    if company is None or not _is_external_manager(user_id):
        return []
    return companies_below(company)
