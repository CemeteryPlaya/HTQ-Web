"""Слепок раскладки тенантных таблиц — ТОЛЬКО чтение.

Зачем. На время доводки структуры группы (docs/plans/2026-09-14-group-
structure-roadmap.md, §3) в реестре одна компания, а модули contracts и
signoff проходят боевые проверки. Каждая выкатка обязана доказать, что их
таблицы на месте и строки не пропали. Команда печатает, где лежит каждая
таблица тенантных аппок (``public`` или ``co_<slug>``), сколько в ней строк,
какие компании есть в реестре и есть ли под ними физические схемы;
``--json`` даёт форму, которую сохраняют и сравнивают diff'ом со слепком
после выкатки.

Ничего не пишет и не блокирует: ``information_schema``,
``pg_stat_user_tables`` (оценка планировщика; ``--exact`` — настоящий
``count(*)`` по каждой таблице, на больших таблицах долго) и реестр.
"""

import json

from django.apps import apps as django_apps
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection
from psycopg import sql

from apps.companies.models import Company
from apps.companies.services import schema_service
from htqweb.tenancy.context import schema_for


def tenant_tables() -> dict[str, list[str]]:
    """app_label -> имена таблиц конкретных моделей тенантной аппки.

    ``include_auto_created=True`` — m2m-таблицы такие же носители данных, и
    забыть их значило бы не заметить их пропажу.

    ``managed=False`` пропускается, как и proxy: модель без таблицы не
    владеет ничем, считать у неё нечего. Единственные такие в проекте —
    читатели холдинга (``apps/hr/holding_models.py``,
    ``apps/tasks/holding_models.py``), чей ``db_table`` намеренно совпадает
    с таблицей компании; без фильтра ``hr_employee`` перечислялась бы в
    аппке дважды. Именно фильтр, а не ``set()``: дедупликация спрятала бы и
    будущий случай двух managed-моделей на одной таблице, который сам по
    себе баг и обязан быть виден.
    """
    out: dict[str, list[str]] = {}
    for label in settings.TENANT_APPS:
        config = django_apps.get_app_config(label)
        out[label] = sorted(
            model._meta.db_table
            for model in config.get_models(include_auto_created=True)
            if not model._meta.proxy and model._meta.managed is not False
        )
    return out


def snapshot(*, exact: bool = False) -> dict:
    tables = tenant_tables()
    label_of = {name: label for label, names in tables.items() for name in names}
    names = sorted(label_of)
    with connection.cursor() as cur:
        cur.execute(
            "SELECT table_schema, table_name FROM information_schema.tables "
            "WHERE table_type = 'BASE TABLE' AND table_name = ANY(%s) "
            "ORDER BY table_schema, table_name",
            [names],
        )
        placed = cur.fetchall()
        cur.execute(
            "SELECT schemaname, relname, n_live_tup FROM pg_stat_user_tables "
            "WHERE relname = ANY(%s)",
            [names],
        )
        estimates = {(s, r): int(n) for s, r, n in cur.fetchall()}
        rows: dict[tuple[str, str], int] = {}
        for schema, table in placed:
            if exact:
                cur.execute(sql.SQL("SELECT count(*) FROM {}.{}").format(
                    sql.Identifier(schema), sql.Identifier(table)))
                rows[(schema, table)] = cur.fetchone()[0]
            else:
                rows[(schema, table)] = estimates.get((schema, table), 0)
        cur.execute(
            "SELECT table_name FROM information_schema.views "
            "WHERE table_schema = 'holding' ORDER BY table_name"
        )
        holding = [row[0] for row in cur.fetchall()]

    schemas: dict[str, dict] = {}
    for (schema, table), count in rows.items():
        entry = schemas.setdefault(schema, {"apps": {}, "tables": {}})
        entry["tables"][table] = count
        app = entry["apps"].setdefault(label_of[table], {"tables": 0, "rows": 0})
        app["tables"] += 1
        app["rows"] += count

    companies = [
        {
            "slug": c.slug, "name": c.name, "kind": c.kind, "status": c.status,
            "schema": schema_for(c.slug),
            "schema_exists": schema_service.schema_exists(c.slug),
        }
        for c in Company.objects.order_by("slug")
    ]
    return {"exact": exact, "companies": companies, "schemas": schemas,
            "holding_views": holding}


def render(data: dict) -> str:
    lines = [f"Реестр: {len(data['companies'])} компани(й)"]
    for c in data["companies"]:
        mark = "есть" if c["schema_exists"] else "НЕТ СХЕМЫ"
        lines.append(
            f"  {c['slug']:<24} {c['name']!r:<34} kind={c['kind']:<13} "
            f"status={c['status']:<9} {c['schema']} ({mark})"
        )
    mode = "точно" if data["exact"] else "оценка планировщика"
    lines.append(f"Таблицы тенантных аппок по схемам (строк — {mode}):")
    labels = list(settings.TENANT_APPS)
    lines.append("  " + f"{'схема':<24}" + "".join(f"{label:>12}" for label in labels)
                 + f"{'строк':>12}")
    for schema, entry in sorted(data["schemas"].items()):
        cells = "".join(
            f"{entry['apps'].get(label, {}).get('tables', 0):>12}" for label in labels
        )
        lines.append(f"  {schema:<24}{cells}{sum(entry['tables'].values()):>12}")
    lines.append(f"Сводки holding: {len(data['holding_views'])} представлени(й)")
    return "\n".join(lines)


class Command(BaseCommand):
    help = "Слепок раскладки тенантных таблиц по схемам (только чтение)."

    def add_arguments(self, parser):
        parser.add_argument("--json", action="store_true", dest="as_json",
                            help="JSON для сравнения слепков до/после выкатки.")
        parser.add_argument("--exact", action="store_true",
                            help="Точный count(*) вместо оценки планировщика.")

    def handle(self, *args, **opts):
        data = snapshot(exact=opts["exact"])
        if opts["as_json"]:
            self.stdout.write(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True))
            return
        self.stdout.write(render(data))
        orphans = [c["slug"] for c in data["companies"]
                   if c["status"] == "active" and not c["schema_exists"]]
        if orphans:
            self.stderr.write(self.style.ERROR(
                "Действующие компании без физической схемы: " + ", ".join(orphans)
                + " — см. CLAUDE.md, «Осиротевшая строка реестра»."
            ))
