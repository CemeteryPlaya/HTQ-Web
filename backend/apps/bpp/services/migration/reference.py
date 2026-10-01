"""Справочники и бюджеты переноса (B6.1, задача 4).

Всё идёт через сервисы модуля, как при ручной работе, — номера, версии и
журнал те же; от человека отличает только исполнитель переноса (``actor``)
и выключенные уведомления. Каждый перенесённый объект — строка
``MigrationLink``: повторный прогон его находит и не заводит второй.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from apps.bpp.models import Budget, Counterparty, CounterpartyKind, CounterpartyStatus
from apps.bpp.services.actor import Actor
from apps.bpp.services.budget import budgets
from apps.project import interface as projects
from htqweb.errors import DomainError

from . import links
from .report import MigrationReport

_CP_STATUS = {"active": CounterpartyStatus.ACTIVE, "inactive": CounterpartyStatus.ARCHIVED,
              "blocked": CounterpartyStatus.BLOCKED}


class MigrationStop(Exception):
    """Перенос не может идти дальше — текст для человека, всё откатывается."""


def _kind(country: str, reg_number: str) -> str:
    """Вида у старого контрагента нет: резидент РК с БИН (5-я цифра 4–6) —
    юрлицо, с ИИН — ИП; прочие страны — нерезидент."""
    if country != "KZ":
        return CounterpartyKind.NONRESIDENT
    digits = "".join(ch for ch in reg_number if ch.isdigit())
    return CounterpartyKind.LEGAL if len(digits) == 12 and digits[4] in "456" \
        else CounterpartyKind.IP


def counterparties(snapshot: dict, report: MigrationReport) -> dict[int, Counterparty]:
    """Все контрагенты — справочник переносится целиком (Q-A05). Уже
    заведённый в модуле (та же страна и рег. номер) переиспользуется."""
    countries = {row["id"]: (row["iso_code"] or "").strip().upper()
                 for row in snapshot["countries"]}
    out = {}
    for row in snapshot["counterparties"]:
        linked = links.target_of("contracts.counterparty", row["id"], "bpp.counterparty")
        if linked:
            out[row["id"]] = Counterparty.objects.get(pk=linked)
            continue
        country = countries.get(row["country_id"]) or "KZ"
        reg_number = row["bin_iin"].strip()
        existing = Counterparty.objects.filter(country_code=country, reg_number=reg_number).first()
        if existing is None:
            existing = Counterparty.objects.create(
                name=row["name"], short_name=row["name"][:255],
                kind=_kind(country, reg_number), country_code=country,
                reg_number=reg_number, is_vat_payer=row["vat"],
                legal_address=row["address"], contact_person=row["contact_name"],
                phone=row["phone"], email=row["email"],
                status=_CP_STATUS.get(row["status"], CounterpartyStatus.ACTIVE))
            action = "создан"
        else:
            action = "найден"
        links.link("contracts.counterparty", row["id"], "bpp.counterparty", existing.pk)
        report.add("Контрагенты", old_id=row["id"], reg_number=reg_number, name=row["name"],
                   action=action)
        out[row["id"]] = existing
    return out


def project_ids(snapshot: dict, project_map: dict[int, dict], actor_id: int,
                report: MigrationReport) -> dict[int, str]:
    """``{admin_id: ключ «Проекта»}`` — по карте; «Проект» с кодом из карты
    уже есть — он и берётся (D-B61-4)."""
    names = {admin["id"]: admin for admin in snapshot["administrators"]}
    out = {}
    for admin_id, entry in project_map.items():
        linked = links.target_of("contracts.administrator", admin_id, "project.project")
        if linked:
            out[admin_id] = linked
            continue
        found = projects.project_ids_by_code([entry["code"]]).get(entry["code"])
        if found:
            action = "найден"
        else:
            members = [entry["manager_user_id"]] if entry["manager_user_id"] else []
            found = projects.create_project(
                code=entry["code"], name=entry["name"], country_code=entry["country"],
                actor_id=actor_id, manager_user_id=entry["manager_user_id"],
                member_ids=members)
            action = "создан"
        if not names[admin_id]["is_active"]:
            action += "; администратор в «Договорах» не активен"
        links.link("contracts.administrator", admin_id, "project.project", found)
        report.add("Проекты", admin_id=admin_id, project_name=entry["name"],
                   project_code=entry["code"], action=action)
        out[admin_id] = found
    return out


def budget_limits(snapshot: dict, article_map: dict[int, dict],
                  report: MigrationReport) -> dict[int, dict]:
    """По администратору: ``{"approved": bool, "years": [...], "limits":
    {article_id: сумма}}`` (D-B61-5). Годы суммируются по статье; не KZT — в
    отчёт без переноса; есть утверждённые годы — в бюджет идут только они."""
    by_admin: dict[int, list[dict]] = defaultdict(list)
    for budget in snapshot["budgets"]:
        if budget["currency"] != "KZT":
            report.add("Не перенесено", kind="бюджет", old_id=budget["id"],
                       reason=f"валюта {budget['currency']} — лимиты модуля в KZT (D-06)")
            continue
        by_admin[budget["administrator_id"]].append(budget)
    out = {}
    for admin_id, rows in by_admin.items():
        approved = [row for row in rows if row["approval_state"] == "approved"]
        taken = approved or rows
        for row in rows:
            if row not in taken:
                report.add("Не перенесено", kind="бюджет", old_id=row["id"],
                           reason=f"{row['period_year']} не утверждён, а у проекта есть "
                                  f"утверждённые годы")
        limits: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
        for row in taken:
            for line in row["lines"]:
                limits[article_map[line["program_id"]]["id"]] += line["amount"]
        out[admin_id] = {"approved": bool(approved),
                         "years": sorted(row["period_year"] for row in taken),
                         "limits": dict(limits)}
    return out


def budgets_for(snapshot: dict, project_by_admin: dict[int, str], article_map: dict[int, dict],
                actor: Actor, report: MigrationReport) -> dict[int, dict]:
    """Бюджет проекта из суммы лет; возвращает лимиты по администратору для
    сверки. У проекта уже есть свой бюджет, не из переноса, — стоп: слить два
    бюджета молча нельзя."""
    plan = budget_limits(snapshot, article_map, report)
    codes = {admin_id: projects.project_brief([pid])[pid]["code"]
             for admin_id, pid in project_by_admin.items()}
    for admin_id, entry in plan.items():
        project_id = project_by_admin[admin_id]
        if links.target_of("contracts.budgets", admin_id, "bpp.budget"):
            continue
        own = Budget.objects.filter(project_id=project_id).first()
        if own is not None:
            raise MigrationStop(f"У проекта {codes[admin_id]} уже есть бюджет {own.number}, "
                                f"заведённый не переносом, — объедините бюджеты вручную.")
        lines = [{"article_id": article_id, "limit_amount": amount}
                 for article_id, amount in entry["limits"].items() if amount > 0]
        if not lines:
            report.add("Не перенесено", kind="бюджет", old_id=admin_id,
                       reason="у проекта нет строк с суммой")
            continue
        try:
            budget = budgets.create(actor, project_id=project_id, lines=lines)
            if entry["approved"]:
                budget = budgets.approve(actor, budget.id, expected_version=None,
                                         notify_parties=False)
        except DomainError as exc:
            raise MigrationStop(f"Бюджет проекта {codes[admin_id]}: {exc.message}") from exc
        links.link("contracts.budgets", admin_id, "bpp.budget", budget.pk)
        report.add("Бюджеты", admin_id=admin_id, project_code=codes[admin_id],
                   years=", ".join(map(str, entry["years"])), number=budget.number,
                   status=budget.get_status_display())
    return plan
