"""Перенос ручных правок производственного календаря из схем компаний в
``refdata.ProductionDay`` (A7.1, D-S7-1) — шаг ранбука после ``migrate_companies``.

Читает ``tasks_productionday`` каждой действующей компании со схемой (сырым
SQL: чужую модель импортировать нельзя, а таблица остаётся до этапа 8).
Правила:

- совпадающие строки разных компаний — одна строка в ``refdata``;
- разный тип дня одной даты (у двух компаний или у компании и в ``refdata``) —
  дата пропускается и попадает в отчёт: решает ОД/HR вручную;
- повтор — ноль изменений; ``--dry-run`` ничего не пишет.

Это команда, а не data-миграция: исключение в миграции уронило бы старт
``backend-web`` (``RUN_MIGRATIONS=1``). Содержимое таблиц на бою неизвестно —
до выкатки прогнать с ``--dry-run``.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import connection, transaction

from apps.companies import interface as companies
from apps.refdata.models import ProductionDay
from apps.refdata.services import production_calendar
from htqweb.tenancy.context import schema_for


def _read_company_rows(slug: str) -> list[tuple]:
    schema = schema_for(slug)
    with connection.cursor() as cur:
        cur.execute("SELECT to_regclass(%s)", [f'"{schema}".tasks_productionday'])
        if cur.fetchone()[0] is None:
            return []
        cur.execute(f'SELECT date, day_type, note FROM "{schema}".tasks_productionday ORDER BY date')
        return cur.fetchall()


class Command(BaseCommand):
    help = "Перенести правки производственного календаря компаний в общий справочник refdata."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="ничего не писать, только отчёт")

    def handle(self, *args, dry_run: bool = False, **options):
        out = self.stdout.write
        # дата -> {слаг компании: (тип, заметка)}
        found: dict = {}
        scanned = no_schema = 0
        for slug in companies.active_company_slugs(fresh=True):
            if not companies.schema_exists(slug):
                no_schema += 1
                out(f"[{slug}] схемы нет — пропуск")
                continue
            scanned += 1
            rows = _read_company_rows(slug)
            out(f"[{slug}] строк календаря: {len(rows)}")
            for day, day_type, note in rows:
                found.setdefault(day, {})[slug] = (day_type, note)

        existing = {row.date: row for row in ProductionDay.objects.all()}
        unchanged = 0
        conflicts: list[str] = []
        to_create: list[ProductionDay] = []
        for day in sorted(found):
            by_company = found[day]
            types = {t for t, _ in by_company.values()}
            if len(types) > 1:
                detail = ", ".join(f"{s}={t}" for s, (t, _) in sorted(by_company.items()))
                conflicts.append(f"{day}: у компаний разный тип дня ({detail})")
                continue
            day_type = types.pop()
            note = next((by_company[s][1] for s in sorted(by_company) if by_company[s][1]), None)
            current = existing.get(day)
            if current is not None:
                if current.day_type == day_type:
                    unchanged += 1
                else:
                    conflicts.append(
                        f"{day}: в refdata «{current.day_type}», у компаний «{day_type}»")
                continue
            to_create.append(ProductionDay(date=day, day_type=day_type, note=note,
                                           working_days_since_epoch=0))

        if not dry_run and to_create:
            with transaction.atomic():
                ProductionDay.objects.bulk_create(to_create)
                for year in sorted({row.date.year for row in to_create}):
                    production_calendar._recalculate_year(year)

        prefix = "[dry-run] " if dry_run else ""
        out(f"{prefix}компаний прочитано: {scanned}, без схемы: {no_schema}")
        out(f"{prefix}добавлено: {len(to_create)}, без изменений: {unchanged}, "
            f"конфликтов: {len(conflicts)}")
        for line in conflicts:
            out(f"КОНФЛИКТ {line}")
