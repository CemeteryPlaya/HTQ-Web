#!/usr/bin/env python3
"""
generate_test_users.py — Idempotent QA test data generator for HTQWeb.

Creates 15 test accounts spanning every role/access level discovered
in the RBAC analysis, along with matching HR records in PostgreSQL
and HR documents in MongoDB.

Usage:
    # Direct execution (requires PostgreSQL and MongoDB access):
    python scripts/generate_test_users.py

    # Dry-run (prints what would be created, no writes):
    python scripts/generate_test_users.py --dry-run

    # Specify connection strings:
    python scripts/generate_test_users.py \
        --pg-dsn "postgresql://htqweb:change-me@localhost:5432/htqweb" \
        --mongo-uri "mongodb://htqweb:change-me-mongo@localhost:27017/htqweb_docs?authSource=admin"

The script is IDEMPOTENT: it checks for existing records by email
before inserting. Safe to run multiple times.

Requirements (pip install):
    psycopg2-binary faker pymongo bcrypt
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from datetime import date, datetime, timezone
from typing import Any

try:
    import bcrypt
    import psycopg2
    import psycopg2.extras
    from faker import Faker
    from pymongo import MongoClient
except ImportError as exc:
    print(f"Missing dependency: {exc.name}")
    print("Install with:  pip install psycopg2-binary faker pymongo bcrypt")
    sys.exit(1)

fake = Faker("ru_RU")
Faker.seed(42)  # reproducible data

# ═══════════════════════════════════════════════════════════════════════════════
# Test user definitions — 15 accounts covering all RBAC levels
# ═══════════════════════════════════════════════════════════════════════════════

TEST_USERS: list[dict[str, Any]] = [
    # ── Superusers ────────────────────────────────────────────────────────────
    {
        "email": "qa_superadmin@htq.test",
        "username": "qa_superadmin",
        "password": "SuperAdmin!2026",
        "first_name": "Алексей",
        "last_name": "Суперов",
        "is_staff": True,
        "is_superuser": True,
        "status": "active",
        "position_title": "Генеральный директор",
        "department": "Руководство",
        "weight": 1,
        "level": 1,
        "grade": 10,
    },
    {
        "email": "qa_superadmin2@htq.test",
        "username": "qa_superadmin2",
        "password": "SuperAdmin2!2026",
        "first_name": "Мария",
        "last_name": "Директорова",
        "is_staff": True,
        "is_superuser": True,
        "status": "active",
        "position_title": "Исполнительный директор",
        "department": "Руководство",
        "weight": 2,
        "level": 1,
        "grade": 10,
    },

    # ── Staff (admin but not superuser) ───────────────────────────────────────
    {
        "email": "qa_staff_admin@htq.test",
        "username": "qa_staff_admin",
        "password": "StaffAdmin!2026",
        "first_name": "Иван",
        "last_name": "Админов",
        "is_staff": True,
        "is_superuser": False,
        "status": "active",
        "position_title": "Системный администратор",
        "department": "IT Отдел",
        "weight": 15,
        "level": 2,
        "grade": 8,
    },
    {
        "email": "qa_staff_hr@htq.test",
        "username": "qa_staff_hr",
        "password": "StaffHR!2026",
        "first_name": "Елена",
        "last_name": "Кадрова",
        "is_staff": True,
        "is_superuser": False,
        "status": "active",
        "position_title": "HR Директор",
        "department": "HR Отдел",
        "weight": 10,
        "level": 2,
        "grade": 9,
    },

    # ── Senior HR (staff — senior level access) ──────────────────────────────
    {
        "email": "qa_senior_hr@htq.test",
        "username": "qa_senior_hr",
        "password": "SeniorHR!2026",
        "first_name": "Ольга",
        "last_name": "Старшая",
        "is_staff": True,
        "is_superuser": False,
        "status": "active",
        "position_title": "Старший HR-менеджер",
        "department": "HR Отдел",
        "weight": 20,
        "level": 2,
        "grade": 7,
    },

    # ── Junior HR (regular employee — no admin flag yet) ─────────────────────
    {
        "email": "qa_junior_hr@htq.test",
        "username": "qa_junior_hr",
        "password": "JuniorHR!2026",
        "first_name": "Анна",
        "last_name": "Младшая",
        "is_staff": False,
        "is_superuser": False,
        "status": "active",
        "position_title": "Младший HR-специалист",
        "department": "HR Отдел",
        "weight": 120,
        "level": 4,
        "grade": 3,
    },

    # ── Recruiter ─────────────────────────────────────────────────────────────
    {
        "email": "qa_recruiter@htq.test",
        "username": "qa_recruiter",
        "password": "Recruiter!2026",
        "first_name": "Дмитрий",
        "last_name": "Рекрутов",
        "is_staff": False,
        "is_superuser": False,
        "status": "active",
        "position_title": "Рекрутер",
        "department": "HR Отдел",
        "weight": 130,
        "level": 4,
        "grade": 3,
    },

    # ── Regular employees (different departments/levels) ─────────────────────
    {
        "email": "qa_senior_dev@htq.test",
        "username": "qa_senior_dev",
        "password": "SeniorDev!2026",
        "first_name": "Сергей",
        "last_name": "Девелоперов",
        "is_staff": False,
        "is_superuser": False,
        "status": "active",
        "position_title": "Старший разработчик",
        "department": "IT Отдел",
        "weight": 55,
        "level": 3,
        "grade": 6,
    },
    {
        "email": "qa_junior_dev@htq.test",
        "username": "qa_junior_dev",
        "password": "JuniorDev!2026",
        "first_name": "Павел",
        "last_name": "Стажёров",
        "is_staff": False,
        "is_superuser": False,
        "status": "active",
        "position_title": "Младший разработчик",
        "department": "IT Отдел",
        "weight": 210,
        "level": 5,
        "grade": 1,
    },
    {
        "email": "qa_manager@htq.test",
        "username": "qa_manager",
        "password": "Manager!2026",
        "first_name": "Наталья",
        "last_name": "Менеджерова",
        "is_staff": False,
        "is_superuser": False,
        "status": "active",
        "position_title": "Менеджер проектов",
        "department": "Управление проектами",
        "weight": 60,
        "level": 3,
        "grade": 5,
    },
    {
        "email": "qa_accountant@htq.test",
        "username": "qa_accountant",
        "password": "Accountant!2026",
        "first_name": "Татьяна",
        "last_name": "Бухгалтерова",
        "is_staff": False,
        "is_superuser": False,
        "status": "active",
        "position_title": "Главный бухгалтер",
        "department": "Финансовый отдел",
        "weight": 30,
        "level": 2,
        "grade": 7,
    },

    # ── Deactivated / special status accounts ────────────────────────────────
    {
        "email": "qa_suspended@htq.test",
        "username": "qa_suspended",
        "password": "Suspended!2026",
        "first_name": "Кирилл",
        "last_name": "Заблокиров",
        "is_staff": False,
        "is_superuser": False,
        "status": "suspended",
        "position_title": "Аналитик данных",
        "department": "IT Отдел",
        "weight": 100,
        "level": 4,
        "grade": 4,
    },
    {
        "email": "qa_pending@htq.test",
        "username": "qa_pending",
        "password": "Pending!2026",
        "first_name": "Артём",
        "last_name": "Ожиданиев",
        "is_staff": False,
        "is_superuser": False,
        "status": "pending",
        "position_title": "Стажёр",
        "department": "IT Отдел",
        "weight": 250,
        "level": 5,
        "grade": 1,
    },
    {
        "email": "qa_rejected@htq.test",
        "username": "qa_rejected",
        "password": "Rejected!2026",
        "first_name": "Максим",
        "last_name": "Отказников",
        "is_staff": False,
        "is_superuser": False,
        "status": "rejected",
        "position_title": "Кандидат",
        "department": "HR Отдел",
        "weight": 260,
        "level": 5,
        "grade": 1,
    },
    {
        "email": "qa_must_change_pw@htq.test",
        "username": "qa_must_change_pw",
        "password": "MustChange!2026",
        "first_name": "Виктория",
        "last_name": "Новичкова",
        "is_staff": False,
        "is_superuser": False,
        "status": "active",
        "must_change_password": True,
        "position_title": "Специалист поддержки",
        "department": "IT Отдел",
        "weight": 140,
        "level": 4,
        "grade": 3,
    },
]

# ── Test departments ─────────────────────────────────────────────────────────
TEST_DEPARTMENTS = [
    {"name": "Руководство", "path": "root", "unit_type": "department"},
    {"name": "HR Отдел", "path": "root.hr", "unit_type": "department"},
    {"name": "IT Отдел", "path": "root.it", "unit_type": "department"},
    {"name": "Управление проектами", "path": "root.pm", "unit_type": "department"},
    {"name": "Финансовый отдел", "path": "root.fin", "unit_type": "department"},
]

# ── MongoDB document templates for each user ─────────────────────────────────
MONGO_DOC_TYPES = ["contract", "order", "certificate", "policy", "memo"]


def _hash_password(password: str) -> str:
    """Hash password using bcrypt (matching user-service auth_service.py)."""
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def _ensure_departments(cur, departments: list[dict]) -> dict[str, int]:
    """Insert departments if not present. Returns name→id mapping."""
    dept_map = {}
    for dept in departments:
        cur.execute(
            "SELECT id FROM hr_departments WHERE name = %s",
            (dept["name"],),
        )
        row = cur.fetchone()
        if row:
            dept_map[dept["name"]] = row[0]
            print(f"  ⏭ Department '{dept['name']}' already exists (id={row[0]})")
        else:
            cur.execute(
                """INSERT INTO hr_departments (name, path, unit_type, is_active, created_at, updated_at)
                   VALUES (%s, %s, %s, true, NOW(), NOW())
                   RETURNING id""",
                (dept["name"], dept["path"], dept["unit_type"]),
            )
            new_id = cur.fetchone()[0]
            dept_map[dept["name"]] = new_id
            print(f"  ✅ Department '{dept['name']}' created (id={new_id})")
    return dept_map


def _ensure_position(cur, title: str, dept_id: int, weight: int, level: int, grade: int) -> int:
    """Insert position if not present. Returns position id."""
    cur.execute("SELECT id FROM hr_positions WHERE title = %s", (title,))
    row = cur.fetchone()
    if row:
        print(f"  ⏭ Position '{title}' already exists (id={row[0]})")
        return row[0]

    # Check weight uniqueness — if weight is taken, offset it
    cur.execute("SELECT id FROM hr_positions WHERE weight = %s", (weight,))
    if cur.fetchone():
        weight = weight + hash(title) % 100 + 1  # deterministic offset

    cur.execute(
        """INSERT INTO hr_positions (title, department_id, grade, weight, level, is_active, created_at, updated_at)
           VALUES (%s, %s, %s, %s, %s, true, NOW(), NOW())
           RETURNING id""",
        (title, dept_id, grade, weight, level),
    )
    new_id = cur.fetchone()[0]
    print(f"  ✅ Position '{title}' created (id={new_id}, weight={weight}, level={level})")
    return new_id


def _ensure_user(cur, user: dict, dry_run: bool = False) -> int | None:
    """Insert user into auth.users if not present. Returns user id."""
    email = user["email"]
    cur.execute("SELECT id FROM users WHERE email = %s", (email,))
    row = cur.fetchone()
    if row:
        print(f"  ⏭ User '{email}' already exists (id={row[0]})")
        return row[0]

    if dry_run:
        print(f"  🔍 [DRY-RUN] Would create user '{email}'")
        return None

    password_hash = _hash_password(user["password"])
    display_name = f"{user['first_name']} {user['last_name']}"

    cur.execute(
        """INSERT INTO users (
               username, email, password_hash,
               first_name, last_name, display_name,
               status, is_staff, is_superuser, must_change_password,
               date_joined, created_at, updated_at
           ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW(), NOW())
           RETURNING id""",
        (
            user["username"],
            email,
            password_hash,
            user["first_name"],
            user["last_name"],
            display_name,
            user["status"],
            user["is_staff"],
            user["is_superuser"],
            user.get("must_change_password", False),
        ),
    )
    new_id = cur.fetchone()[0]
    role_info = []
    if user["is_superuser"]:
        role_info.append("superuser")
    if user["is_staff"]:
        role_info.append("staff")
    if not role_info:
        role_info.append("employee")
    print(f"  ✅ User '{email}' created (id={new_id}, roles={role_info}, status={user['status']})")
    return new_id


def _ensure_employee(
    cur, user: dict, user_id: int, dept_id: int, position_id: int, dry_run: bool = False
) -> int | None:
    """Insert employee record if not present. Returns employee id."""
    email = user["email"]
    cur.execute("SELECT id FROM hr_employees WHERE email = %s", (email,))
    row = cur.fetchone()
    if row:
        print(f"  ⏭ Employee '{email}' already exists (id={row[0]})")
        return row[0]

    if dry_run:
        print(f"  🔍 [DRY-RUN] Would create employee '{email}'")
        return None

    cur.execute(
        """INSERT INTO hr_employees (
               user_id, first_name, last_name, email,
               department_id, position_id, hire_date,
               status, is_deleted, created_at, updated_at
           ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, false, NOW(), NOW())
           RETURNING id""",
        (
            user_id,
            user["first_name"],
            user["last_name"],
            email,
            dept_id,
            position_id,
            date.today().isoformat(),
            user["status"],
        ),
    )
    new_id = cur.fetchone()[0]
    print(f"  ✅ Employee '{email}' created (id={new_id})")
    return new_id


def _generate_mongo_docs(
    mongo_db, employee_id: int, user: dict, dry_run: bool = False
) -> int:
    """Generate 2-3 fake HR documents in MongoDB for the employee."""
    if employee_id is None:
        return 0

    coll = mongo_db["hr_documents"]

    # Check if docs already exist for this employee
    existing = coll.count_documents({"sql_employee_id": employee_id})
    if existing > 0:
        print(f"  ⏭ MongoDB docs for employee {employee_id} already exist ({existing} docs)")
        return 0

    if dry_run:
        print(f"  🔍 [DRY-RUN] Would create MongoDB docs for employee {employee_id}")
        return 0

    docs_to_insert = []
    now = datetime.now(timezone.utc)

    # Always create a contract
    docs_to_insert.append({
        "sql_employee_id": employee_id,
        "title": f"Трудовой договор — {user['first_name']} {user['last_name']}",
        "doc_type": "contract",
        "content": fake.text(max_nb_chars=500),
        "file_url": None,
        "file_size_bytes": fake.random_int(min=50000, max=2000000),
        "mime_type": "application/pdf",
        "tags": ["трудовой", "договор", "HR"],
        "metadata": {
            "contract_number": f"TD-{fake.random_int(min=1000, max=9999)}",
            "contract_date": date.today().isoformat(),
            "salary_currency": "KZT",
        },
        "created_by_user_id": 1,  # assumed admin
        "created_at": now,
        "updated_at": now,
    })

    # Create an order for active employees
    if user["status"] == "active":
        docs_to_insert.append({
            "sql_employee_id": employee_id,
            "title": f"Приказ о приёме на работу — {user['first_name']} {user['last_name']}",
            "doc_type": "order",
            "content": fake.text(max_nb_chars=300),
            "file_url": None,
            "file_size_bytes": fake.random_int(min=20000, max=500000),
            "mime_type": "application/pdf",
            "tags": ["приказ", "приём", "HR"],
            "metadata": {
                "order_number": f"PR-{fake.random_int(min=100, max=999)}",
                "order_date": date.today().isoformat(),
            },
            "created_by_user_id": 1,
            "created_at": now,
            "updated_at": now,
        })

    # Performance review for senior employees
    if user.get("weight", 100) < 100:
        docs_to_insert.append({
            "sql_employee_id": employee_id,
            "title": f"Отчёт об аттестации — {user['first_name']} {user['last_name']}",
            "doc_type": "performance_review",
            "content": fake.text(max_nb_chars=800),
            "file_url": None,
            "file_size_bytes": fake.random_int(min=100000, max=5000000),
            "mime_type": "application/pdf",
            "tags": ["аттестация", "оценка", "HR"],
            "metadata": {
                "review_period": "2025-H2",
                "score": fake.random_int(min=3, max=5),
                "reviewer": "HR Director",
            },
            "created_by_user_id": 1,
            "created_at": now,
            "updated_at": now,
        })

    result = coll.insert_many(docs_to_insert)
    count = len(result.inserted_ids)
    print(f"  ✅ {count} MongoDB doc(s) created for employee {employee_id}")
    return count


def main():
    parser = argparse.ArgumentParser(
        description="Generate test users for HTQWeb QA (idempotent)"
    )
    parser.add_argument(
        "--pg-dsn",
        default="postgresql://htqweb:change-me@localhost:5432/htqweb",
        help="PostgreSQL connection string",
    )
    parser.add_argument(
        "--mongo-uri",
        default="mongodb://htqweb:change-me-mongo@localhost:27017/htqweb_docs?authSource=admin",
        help="MongoDB connection string",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be created without writing",
    )
    args = parser.parse_args()

    print("=" * 70)
    print("HTQWeb QA — Test Data Generator")
    print(f"Mode: {'DRY-RUN' if args.dry_run else 'LIVE'}")
    print("=" * 70)

    # ── Connect PostgreSQL ───────────────────────────────────────────────────
    print("\n📦 Connecting to PostgreSQL...")
    try:
        pg_conn = psycopg2.connect(args.pg_dsn)
        pg_conn.autocommit = False
        pg_cur = pg_conn.cursor()
        print("  ✅ PostgreSQL connected")
    except Exception as exc:
        print(f"  ❌ PostgreSQL connection failed: {exc}")
        sys.exit(1)

    # ── Connect MongoDB ──────────────────────────────────────────────────────
    print("\n📦 Connecting to MongoDB...")
    mongo_client = None
    mongo_db = None
    try:
        mongo_client = MongoClient(args.mongo_uri, serverSelectionTimeoutMS=5000)
        mongo_client.admin.command("ping")
        mongo_db = mongo_client["htqweb_docs"]
        print("  ✅ MongoDB connected")
    except Exception as exc:
        print(f"  ⚠️  MongoDB connection failed: {exc}")
        print("  → MongoDB documents will be skipped")

    # ── Create departments (PostgreSQL, public schema) ───────────────────────
    print("\n🏢 Ensuring test departments...")
    try:
        pg_cur.execute("SET search_path TO public")
        dept_map = _ensure_departments(pg_cur, TEST_DEPARTMENTS)
        if not args.dry_run:
            pg_conn.commit()
    except Exception as exc:
        pg_conn.rollback()
        print(f"  ❌ Failed to create departments: {exc}")
        sys.exit(1)

    # ── Create positions + users + employees ─────────────────────────────────
    print("\n👥 Processing test users...")
    total_users = 0
    total_employees = 0
    total_docs = 0

    for user in TEST_USERS:
        print(f"\n--- {user['email']} ---")

        # Position (public schema)
        dept_name = user["department"]
        dept_id = dept_map.get(dept_name)
        if dept_id is None:
            print(f"  ❌ Department '{dept_name}' not found — skipping")
            continue

        try:
            pg_cur.execute("SET search_path TO public")
            position_id = _ensure_position(
                pg_cur,
                user["position_title"],
                dept_id,
                user["weight"],
                user["level"],
                user["grade"],
            )
            if not args.dry_run:
                pg_conn.commit()
        except Exception as exc:
            pg_conn.rollback()
            print(f"  ❌ Position failed: {exc}")
            continue

        # User (auth schema? No, it's in public schema)
        try:
            pg_cur.execute("SET search_path TO public")
            user_id = _ensure_user(pg_cur, user, dry_run=args.dry_run)
            if not args.dry_run:
                pg_conn.commit()
            if user_id:
                total_users += 1
        except Exception as exc:
            pg_conn.rollback()
            print(f"  ❌ User creation failed: {exc}")
            continue

        # Employee (public schema)
        if user_id and user["status"] in ("active", "suspended"):
            try:
                pg_cur.execute("SET search_path TO public")
                employee_id = _ensure_employee(
                    pg_cur, user, user_id, dept_id, position_id, dry_run=args.dry_run
                )
                if not args.dry_run:
                    pg_conn.commit()
                if employee_id:
                    total_employees += 1

                # MongoDB documents
                if mongo_db is not None and employee_id:
                    doc_count = _generate_mongo_docs(
                        mongo_db, employee_id, user, dry_run=args.dry_run
                    )
                    total_docs += doc_count
            except Exception as exc:
                pg_conn.rollback()
                print(f"  ❌ Employee/docs failed: {exc}")
                continue

    # ── Summary ──────────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("📊 Summary:")
    print(f"  Users processed:     {total_users}")
    print(f"  Employees created:   {total_employees}")
    print(f"  MongoDB docs:        {total_docs}")
    print(f"  Departments:         {len(dept_map)}")
    print("=" * 70)

    if not args.dry_run:
        print("\n🔑 Test credentials (password format: <Role>!2026):")
        print("-" * 70)
        print(f"{'Email':<35} {'Password':<20} {'Role'}")
        print("-" * 70)
        for user in TEST_USERS:
            roles = []
            if user["is_superuser"]:
                roles.append("superuser")
            elif user["is_staff"]:
                roles.append("staff")
            else:
                roles.append("employee")
            if user["status"] != "active":
                roles.append(f"[{user['status']}]")
            if user.get("must_change_password"):
                roles.append("[must_change_pw]")
            print(f"  {user['email']:<35} {user['password']:<20} {', '.join(roles)}")
        print("-" * 70)

    # ── Cleanup ──────────────────────────────────────────────────────────────
    pg_cur.close()
    pg_conn.close()
    if mongo_client:
        mongo_client.close()

    print("\n✅ Done!")


if __name__ == "__main__":
    main()
