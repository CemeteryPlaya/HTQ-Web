#!/usr/bin/env python3
"""
generate_test_tasks.py — Idempotent QA test tasks for the Tasks / Gantt module.

Creates a realistic set of tasks (keys ``QA-*``) in ``public.tasks`` with varied
assignees, statuses and start/due/completed dates so the **Gantt chart** in
Reports (Задачи → Отчёты → Гантт) and the per-employee schedule have data.

It also seeds the task-service replica tables (``task_users``, ``task_departments``)
from the QA accounts created by ``generate_test_users.py`` — these are normally
populated by the user/hr sync, but for local QA we fill them directly.

Usage:
    python scripts/generate_test_tasks.py
    python scripts/generate_test_tasks.py --dry-run
    python scripts/generate_test_tasks.py --reset        # delete existing QA-* tasks first
    python scripts/generate_test_tasks.py \
        --pg-dsn "postgresql://htqweb:change-me@localhost:5432/htqweb"

IDEMPOTENT: skips tasks whose key already exists. Safe to run repeatedly.

Requirements:
    pip install psycopg2-binary
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timedelta

try:
    import psycopg2
except ImportError as exc:  # pragma: no cover
    print(f"Missing dependency: {exc.name}")
    print("Install with:  pip install psycopg2-binary")
    sys.exit(1)

TODAY = date.today()
KEY_PREFIX = "QA-"

# Pool of work items: (summary, task_type, priority)
WORK_ITEMS: list[tuple[str, str, str]] = [
    ("Сбор требований к модулю отчётности", "story", "high"),
    ("Проектирование схемы БД", "task", "high"),
    ("Реализация API задач", "task", "medium"),
    ("Вёрстка диаграммы Ганта", "task", "medium"),
    ("Исправить баг с фильтрами задач", "bug", "high"),
    ("Интеграция с user-service", "task", "medium"),
    ("Настройка CI/CD пайплайна", "task", "low"),
    ("Код-ревью спринта", "task", "medium"),
    ("Подготовка демо для заказчика", "story", "high"),
    ("Оптимизация SQL-запросов", "task", "low"),
    ("Написание e2e-тестов", "task", "medium"),
    ("Обновление документации API", "task", "trivial"),
    ("Миграция исторических данных", "task", "high"),
    ("Рефакторинг UI-компонентов", "task", "low"),
    ("Аудит безопасности сервиса", "task", "critical"),
    ("Релиз версии 1.0", "epic", "critical"),
]

# Equipment fleet: (name, inventory_no, category)
EQUIPMENT: list[tuple[str, str, str]] = [
    ("Экскаватор CAT 320", "EQ-001", "Спецтехника"),
    ("Бетономешалка КамАЗ", "EQ-002", "Транспорт"),
    ("Башенный кран Liebherr", "EQ-003", "Кран"),
    ("Сервер Dell R740", "EQ-004", "IT-оборудование"),
    ("Автовышка ВС-22", "EQ-005", "Спецтехника"),
]

# Lifecycle phases: (status, start_offset_days, duration_days)
# Negative offset = in the past (relative to today).
PHASES: list[tuple[str, int, int]] = [
    # ── Завершённые (с фактической датой выполнения) ──
    ("done",        -56, 8),
    ("closed",      -49, 6),
    ("done",        -42, 10),
    ("done",        -35, 5),
    ("closed",      -30, 7),
    ("done",        -22, 12),
    # ── В работе / на ревью (пересекают «сегодня») ──
    ("in_progress", -10, 16),
    ("in_progress",  -6, 12),
    ("in_review",    -8, 10),
    ("in_progress",  -3, 18),
    ("in_progress",  -1, 11),
    # ── Запланированные (в будущем) ──
    ("open",          2, 9),
    ("open",          6, 12),
    ("open",         11, 7),
    ("open",         16, 14),
    ("open",         22, 8),
]


def _seed_replicas(cur, dry_run: bool) -> list[tuple[int, int | None]]:
    """Populate task_departments + task_users from QA accounts.

    Returns list of (user_id, department_id) for active QA assignees.
    """
    # Departments first (FK target for task_users.department_id).
    cur.execute(
        """
        INSERT INTO task_departments (id, name)
        SELECT id, name FROM hr_departments
        ON CONFLICT (id) DO NOTHING
        """
    )
    print(f"  ✅ task_departments synced ({cur.rowcount} new)")

    # Users (replica) — pull department from the HR employee record when present.
    cur.execute(
        """
        INSERT INTO task_users (id, username, email, first_name, last_name, department_id, is_active)
        SELECT u.id, u.username, u.email, u.first_name, u.last_name, e.department_id, true
        FROM users u
        LEFT JOIN hr_employees e ON e.user_id = u.id
        WHERE u.email LIKE 'qa_%%@htq.test' AND u.status = 'active'
        ON CONFLICT (id) DO NOTHING
        """
    )
    print(f"  ✅ task_users synced ({cur.rowcount} new)")

    cur.execute(
        """
        SELECT id, department_id FROM task_users
        WHERE email LIKE 'qa_%%@htq.test'
        ORDER BY id
        """
    )
    assignees = cur.fetchall()
    print(f"  → {len(assignees)} QA assignee(s) available")
    return assignees


def _seed_equipment(cur, dry_run: bool) -> list[int]:
    """Ensure the equipment fleet exists (by name). Returns equipment ids."""
    ids: list[int] = []
    for name, inv, cat in EQUIPMENT:
        cur.execute("SELECT id FROM task_equipment WHERE name = %s", (name,))
        row = cur.fetchone()
        if row:
            ids.append(row[0])
            continue
        if dry_run:
            print(f"  🔍 [DRY] equipment '{name}'")
            continue
        cur.execute(
            """
            INSERT INTO task_equipment (name, inventory_no, category, is_active, created_at, updated_at)
            VALUES (%s, %s, %s, true, NOW(), NOW()) RETURNING id
            """,
            (name, inv, cat),
        )
        ids.append(cur.fetchone()[0])
    print(f"  ✅ equipment fleet: {len(ids)} unit(s)")
    return ids


def _attach_equipment(cur, equipment_ids: list[int], dry_run: bool) -> int:
    """Attach equipment to existing QA-* tasks (idempotent). Returns count created."""
    if not equipment_ids:
        return 0
    cur.execute("SELECT id FROM tasks WHERE key LIKE %s ORDER BY id", (KEY_PREFIX + "%",))
    task_ids = [r[0] for r in cur.fetchall()]
    created = 0
    # Attach one machine to roughly every task in the first 15 (3 per machine).
    for i, task_id in enumerate(task_ids[:15]):
        eq_id = equipment_ids[i % len(equipment_ids)]
        cur.execute(
            "SELECT 1 FROM task_assignments WHERE task_id = %s AND equipment_id = %s",
            (task_id, eq_id),
        )
        if cur.fetchone():
            continue
        if dry_run:
            created += 1
            continue
        cur.execute(
            """
            INSERT INTO task_assignments (task_id, equipment_id, allocation, created_at, updated_at)
            VALUES (%s, %s, 100, NOW(), NOW())
            """,
            (task_id, eq_id),
        )
        created += 1
    print(f"  ✅ equipment assignments: {created} new")
    return created


def _phase_dates(status: str, start_off: int, dur: int):
    start = TODAY + timedelta(days=start_off)
    due = start + timedelta(days=dur)
    completed = None
    if status in ("done", "closed"):
        comp = min(due, TODAY)  # выполнено не позже сегодня
        completed = datetime(comp.year, comp.month, comp.day, 12, 0, 0)
    return start, due, completed


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate QA test tasks (idempotent)")
    parser.add_argument(
        "--pg-dsn",
        default="postgresql://htqweb:change-me@localhost:5432/htqweb",
        help="PostgreSQL connection string",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print, do not write")
    parser.add_argument(
        "--reset", action="store_true", help="Delete existing QA-* tasks before seeding"
    )
    parser.add_argument(
        "--count", type=int, default=24, help="Number of tasks to create (default 24)"
    )
    parser.add_argument(
        "--reporter-id", type=int, default=1, help="task_users.id used as reporter (default 1)"
    )
    args = parser.parse_args()

    print("=" * 70)
    print("HTQWeb QA — Test Tasks Generator")
    print(f"Mode: {'DRY-RUN' if args.dry_run else 'LIVE'}  ·  Today: {TODAY.isoformat()}")
    print("=" * 70)

    print("\n📦 Connecting to PostgreSQL...")
    try:
        conn = psycopg2.connect(args.pg_dsn)
        conn.autocommit = False
        cur = conn.cursor()
        cur.execute("SET search_path TO public")
        print("  ✅ Connected")
    except Exception as exc:
        print(f"  ❌ Connection failed: {exc}")
        sys.exit(1)

    try:
        if args.reset and not args.dry_run:
            cur.execute("DELETE FROM tasks WHERE key LIKE %s", (KEY_PREFIX + "%",))
            print(f"\n🧹 Removed {cur.rowcount} existing {KEY_PREFIX}* task(s)")

        print("\n👥 Seeding replica tables...")
        assignees = _seed_replicas(cur, args.dry_run)
        if not assignees:
            print("  ❌ No QA assignees found. Run scripts/generate_test_users.py first.")
            conn.rollback()
            sys.exit(1)

        print("\n🗂  Creating tasks...")
        created = skipped = 0
        for i in range(args.count):
            summary, ttype, priority = WORK_ITEMS[i % len(WORK_ITEMS)]
            status, soff, dur = PHASES[i % len(PHASES)]
            assignee_id, dept_id = assignees[i % len(assignees)]
            start, due, completed = _phase_dates(status, soff, dur)
            key = f"{KEY_PREFIX}{i + 1}"

            cur.execute("SELECT 1 FROM tasks WHERE key = %s", (key,))
            if cur.fetchone():
                skipped += 1
                continue

            if args.dry_run:
                print(f"  🔍 [DRY] {key:<7} {status:<12} {start}→{due} "
                      f"assignee={assignee_id} · {summary}")
                created += 1
                continue

            cur.execute(
                """
                INSERT INTO tasks (
                    key, summary, description,
                    task_type, priority, status,
                    reporter_id, assignee_id, department_id,
                    due_date, start_date, completed_at,
                    is_deleted, created_at, updated_at
                ) VALUES (
                    %s, %s, %s,
                    %s::tasktype, %s::priority, %s::status,
                    %s, %s, %s,
                    %s, %s, %s,
                    false, NOW(), NOW()
                )
                """,
                (
                    key, summary, f"Тестовая задача ({status}) для проверки диаграммы Ганта.",
                    ttype, priority, status,
                    args.reporter_id, assignee_id, dept_id,
                    due, start, completed,
                ),
            )
            created += 1

        print("\n🚜 Seeding equipment fleet + assignments...")
        equipment_ids = _seed_equipment(cur, args.dry_run)
        eq_assigned = _attach_equipment(cur, equipment_ids, args.dry_run)

        if args.dry_run:
            conn.rollback()
        else:
            conn.commit()

        print("\n" + "=" * 70)
        print(f"📊 Tasks created: {created}   ·   skipped (existing): {skipped}")
        print(f"   Equipment: {len(equipment_ids)} unit(s) · {eq_assigned} new assignment(s)")
        print(f"   Keys: {KEY_PREFIX}1 … {KEY_PREFIX}{args.count}")
        print("   Смотреть: Задачи → Отчёты → вкладка «Гантт» (/tasks/reports)")
        print("=" * 70)
    except Exception as exc:
        conn.rollback()
        print(f"\n❌ Failed: {exc}")
        sys.exit(1)
    finally:
        cur.close()
        conn.close()

    print("\n✅ Done!")


if __name__ == "__main__":
    main()
