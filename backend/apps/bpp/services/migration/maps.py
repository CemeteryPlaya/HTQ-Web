"""Карты переноса «администратор → Проект» и «программа → статья» (B6.1,
D-B61-3, D-B61-4).

Код «Проекта» неизменяем, а статьи ведёт управляющая компания, поэтому обе
карты заполняет человек: команда строит черновики (``--draft-maps``), ФД
правит их и передаёт обратно. Проверка карты — до первой записи: любой
пропуск останавливает перенос с перечнем, а не переносит «сколько вышло».

CSV — с разделителем «;» и BOM: так файл открывается в Excel с русской
локалью без мастера импорта. Читается и «,» — если файл сохранили иначе.
"""

from __future__ import annotations

import csv
from pathlib import Path

from apps.project import interface as projects
from apps.refdata import interface as refdata

PROJECT_COLUMNS = ("admin_id", "project_name", "country", "project_code", "manager_user_id")
ARTICLE_COLUMNS = ("program_id", "program_code", "program_name", "expense_item", "used_by",
                   "article_code")
_CODE_MAX = 32


# ── справочники платформы ───────────────────────────────────────────────

def article_index() -> dict[str, dict]:
    """Действующие статьи по коду: ``{код: {id, code, name, group}}``."""
    index = {}
    for group in refdata.article_groups():
        for article in refdata.active_articles(group["code"]):
            index[article["code"]] = {**article, "group": group["code"]}
    return index


def _countries(snapshot: dict) -> dict[int, str]:
    return {row["id"]: (row["iso_code"] or "").strip().upper() for row in snapshot["countries"]}


# ── что переносится ──────────────────────────────────────────────────────

def used_administrator_ids(snapshot: dict) -> set[int]:
    """Администраторы с бюджетом или подотчётом старого вида (без строки)."""
    ids = {budget["administrator_id"] for budget in snapshot["budgets"]}
    ids |= {row["administrator_id"] for row in snapshot["accountable"]
            if row["budget_line_id"] is None and row["administrator_id"]}
    return ids


def used_program_ids(snapshot: dict) -> set[int]:
    ids = {line["program_id"] for budget in snapshot["budgets"] for line in budget["lines"]}
    ids |= {row["program_id"] for row in snapshot["accountable"]
            if row["budget_line_id"] is None and row["program_id"]}
    return ids


# ── черновики ────────────────────────────────────────────────────────────

def draft_projects(snapshot: dict) -> list[dict]:
    """Строка на администратора. «Проект» с тем же названием уже есть —
    его код; иначе ``П-<id администратора>`` — ФД правит до переноса."""
    countries = _countries(snapshot)
    used = used_administrator_ids(snapshot)
    rows = []
    for admin in snapshot["administrators"]:
        if admin["id"] not in used:
            continue
        same = [row for row in projects.search_projects(admin["project_name"], user_id=0,
                                                        only_member=False, limit=50)
                if row["name"] == admin["project_name"]]
        rows.append({
            "admin_id": admin["id"], "project_name": admin["project_name"],
            "country": countries.get(admin["country_id"], ""),
            "project_code": same[0]["code"] if same else f"П-{admin['id']}",
            "manager_user_id": admin["user_id"] or "",
        })
    return rows


def draft_articles(snapshot: dict, articles: dict[str, dict]) -> tuple[list[dict], list[str]]:
    """Строка на используемую программу; статья предложена, если её код
    совпал с кодом программы. Второе — конфликты кодов: один код у разных
    программ (у финансистов коды свои в каждом проекте) — такую программу
    по коду не сопоставить, только картой."""
    admin_names = {admin["id"]: admin["project_name"] for admin in snapshot["administrators"]}
    users: dict[int, set[str]] = {}
    for budget in snapshot["budgets"]:
        for line in budget["lines"]:
            users.setdefault(line["program_id"], set()).add(admin_names[budget["administrator_id"]])
    used = used_program_ids(snapshot)
    programs = [row for row in snapshot["programs"] if row["id"] in used]
    by_code: dict[str, set[str]] = {}
    for program in programs:
        if program["code"]:
            by_code.setdefault(program["code"], set()).add(program["name"])
    conflicts = [f"Код программы {code} — у разных программ: {', '.join(sorted(names))}"
                 for code, names in sorted(by_code.items()) if len(names) > 1]
    rows = [{
        "program_id": program["id"], "program_code": program["code"],
        "program_name": program["name"], "expense_item": program["expense_item"],
        "used_by": ", ".join(sorted(users.get(program["id"], ()))),
        "article_code": program["code"] if program["code"] in articles
        and len(by_code.get(program["code"], ())) == 1 else "",
    } for program in programs]
    return rows, conflicts


def write_csv(path: Path, columns, rows) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns), delimiter=";")
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path: Path, columns) -> list[dict]:
    text = Path(path).read_text(encoding="utf-8-sig")
    delimiter = ";" if text.split("\n", 1)[0].count(";") >= text.split("\n", 1)[0].count(",") \
        else ","
    rows = list(csv.DictReader(text.splitlines(), delimiter=delimiter))
    missing = [column for column in columns if rows and column not in rows[0]]
    if missing:
        raise ValueError(f"В файле {Path(path).name} нет колонок: {', '.join(missing)}")
    return [{key: (value or "").strip() for key, value in row.items()} for row in rows]


# ── проверка ─────────────────────────────────────────────────────────────

def check_projects(rows: list[dict], snapshot: dict) -> tuple[dict[int, dict], list[str]]:
    """``{admin_id: {code, name, country, manager_user_id}}`` и ошибки."""
    errors, result, seen, faulty = [], {}, {}, set()
    countries = _countries(snapshot)
    admins = {admin["id"]: admin for admin in snapshot["administrators"]}
    known = refdata.country_brief(sorted({code for code in countries.values() if code}))
    for row in rows:
        try:
            admin_id = int(row["admin_id"])
        except ValueError:
            errors.append(f"Карта проектов: неверный admin_id «{row['admin_id']}»")
            continue
        code = row["project_code"]
        if admin_id not in admins:
            errors.append(f"Карта проектов: администратора {admin_id} нет в «Договорах»")
            continue
        if not code or len(code) > _CODE_MAX:
            faulty.add(admin_id)
            errors.append(f"Администратор {admin_id} «{admins[admin_id]['project_name']}»: "
                          f"код проекта пуст или длиннее {_CODE_MAX} символов")
            continue
        if code in seen:
            faulty.add(admin_id)
            errors.append(f"Код проекта {code} повторяется: администраторы {seen[code]} и {admin_id}")
            continue
        seen[code] = admin_id
        country = countries.get(admins[admin_id]["country_id"], "")
        if not country or country not in known or not known[country]["is_active"]:
            faulty.add(admin_id)
            errors.append(f"Администратор {admin_id}: страны «{country or 'без кода ISO'}» нет "
                          f"в справочнике стран")
            continue
        manager = row.get("manager_user_id") or ""
        result[admin_id] = {"code": code, "name": admins[admin_id]["project_name"],
                            "country": country, "manager_user_id": int(manager) if manager else None}
    for admin_id in sorted(used_administrator_ids(snapshot) - set(result) - faulty):
        errors.append(f"Карта проектов: нет строки администратора {admin_id} "
                      f"«{admins[admin_id]['project_name']}»")
    return result, errors


def check_articles(rows: list[dict], snapshot: dict,
                   articles: dict[str, dict]) -> tuple[dict[int, dict], list[str]]:
    """``{program_id: статья}`` и ошибки: пустая или несуществующая статья —
    стоп (D-B61-3: недостающие статьи УК заводит в «Справочниках»)."""
    errors, result, faulty = [], {}, set()
    programs = {program["id"]: program for program in snapshot["programs"]}
    for row in rows:
        try:
            program_id = int(row["program_id"])
        except ValueError:
            errors.append(f"Карта статей: неверный program_id «{row['program_id']}»")
            continue
        program = programs.get(program_id)
        label = f"{program['code']} {program['name']}".strip() if program else str(program_id)
        code = row["article_code"]
        if program is not None and program_id not in result:
            faulty.add(program_id)
        if program is None:
            errors.append(f"Карта статей: программы {program_id} нет в «Договорах»")
        elif not code:
            errors.append(f"Программа {label}: не указана статья")
        elif code not in articles:
            errors.append(f"Программа {label}: статьи {code} нет в справочнике — заведите её "
                          f"в «Справочниках» или поправьте карту")
        else:
            faulty.discard(program_id)
            result[program_id] = articles[code]
    for program_id in sorted(used_program_ids(snapshot) - set(result) - faulty):
        program = programs[program_id]
        label = f"{program['code']} {program['name']}".strip()
        errors.append(f"Карта статей: нет строки программы {program_id} «{label}»")
    return result, errors
