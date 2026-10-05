"""Карты импорта книги CashFlow (B6.2, D-B62-5): «администратор → Проект» и
«администратор × код программы → статья».

То же, что карты переноса «Договоров» (``migration/maps.py``), только ключи —
названия из самой книги: идентификаторов в ней нет. Коды программ у
финансистов свои в каждом проекте (3026 у Аральска и 3026 у «Арал 30 МВт» —
разные программы), поэтому статья ищется по паре с администратором.
"""

from __future__ import annotations

from apps.bpp.services.migration.maps import article_index, read_csv, write_csv  # noqa: F401
from apps.project import interface as projects
from apps.refdata import interface as refdata

PROJECT_COLUMNS = ("administrator", "project_code", "country", "manager_user_id")
ARTICLE_COLUMNS = ("administrator", "program_code", "program_name", "article_code")
_CODE_MAX = 32


def administrators(budget, registry, operations) -> list[str]:
    names = {row.administrator for row in (*budget, *registry, *operations)}
    return sorted(name for name in names if name)


def programs(budget, registry, operations) -> dict[tuple[str, str], str]:
    """``{(администратор, код): название}`` — всё, на что книга ссылается.
    Название — с листа «Бюджет» (полное), иначе из реестра или операции."""
    out: dict[tuple[str, str], str] = {}
    for row in budget:
        if row.program_code:
            out[(row.administrator, row.program_code)] = row.program_name
    for row in (*registry, *operations):
        if row.program_code:
            out.setdefault((row.administrator, row.program_code), row.program_name)
    return out


def draft_projects(names: list[str]) -> list[dict]:
    """Строка на администратора; «Проект» с тем же названием уже есть
    (например, заведён переносом «Договоров») — его код, иначе пусто: код
    неизменяем, его задаёт ФД."""
    rows = []
    for name in names:
        same = [row for row in projects.search_projects(name, user_id=0, only_member=False,
                                                        limit=50) if row["name"] == name]
        rows.append({"administrator": name, "project_code": same[0]["code"] if same else "",
                     "country": "KZ", "manager_user_id": ""})
    return rows


def draft_articles(used: dict[tuple[str, str], str], articles: dict[str, dict]) -> list[dict]:
    return [{"administrator": admin, "program_code": code, "program_name": name,
             "article_code": code if code in articles else ""}
            for (admin, code), name in sorted(used.items())]


def check_projects(rows: list[dict], names: list[str]) -> tuple[dict[str, dict], list[str]]:
    errors, result, seen = [], {}, {}
    known = refdata.country_brief(sorted({(row.get("country") or "KZ").upper()
                                          for row in rows}))
    for row in rows:
        name, code = row["administrator"], row["project_code"]
        country = (row.get("country") or "KZ").upper()
        if not code or len(code) > _CODE_MAX:
            errors.append(f"«{name}»: код проекта пуст или длиннее {_CODE_MAX} символов")
        elif code in seen:
            errors.append(f"Код проекта {code} повторяется: «{seen[code]}» и «{name}»")
        elif country not in known or not known[country]["is_active"]:
            errors.append(f"«{name}»: страны {country} нет в справочнике стран")
        else:
            seen[code] = name
            manager = row.get("manager_user_id") or ""
            result[name] = {"code": code, "name": name, "country": country,
                            "manager_user_id": int(manager) if manager else None}
    listed = {row["administrator"] for row in rows}
    errors += [f"Карта проектов: нет строки администратора «{name}»"
               for name in names if name not in listed]
    return result, errors


def check_articles(rows: list[dict], used: dict[tuple[str, str], str],
                   articles: dict[str, dict]) -> tuple[dict[tuple[str, str], dict], list[str]]:
    errors, result = [], {}
    for row in rows:
        key = (row["administrator"], row["program_code"])
        label = f"«{key[0]}» {key[1]} {row.get('program_name', '')}".rstrip()
        code = row["article_code"]
        if not code:
            errors.append(f"{label}: не указана статья")
        elif code not in articles:
            errors.append(f"{label}: статьи {code} нет в справочнике — заведите её в "
                          f"«Справочниках» или поправьте карту")
        else:
            result[key] = articles[code]
    listed = {(row["administrator"], row["program_code"]) for row in rows}
    errors += [f"Карта статей: нет строки «{admin}» {code}" for admin, code in sorted(used)
               if (admin, code) not in listed]
    return result, errors
