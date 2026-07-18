"""Idempotent demo-data seeder for the HR sidebar pages.

Single source of truth for the demo records used by:
- the ``scripts/seed_demo.py`` CLI shim (one-shot manual run);
- the lifespan hook in ``app/main.py`` (auto-seed on dev/staging startup).

The shape of the demo org follows a non-profit-style chart:
- Board of Directors (phantom position — no holder, governance unit)
- CEO reports to the Board
- Advisory Board (phantom position — no holder) plus Staff Director and
  Volunteer Director report to the CEO
- Five operational directors (Finance, Communications, Fundraising, Programs,
  Operations) report to the CEO; each has two specialists.

Idempotency rules:
- ``LevelThreshold`` rows are seeded by Alembic migration 002. We only
  *backfill* the colour column for rows where it is still ``NULL`` — never
  overwrite a colour an admin has chosen via ``/admin/levels``.
- Departments / positions / employees / reporting relations are upserted by
  natural unique key. Existing rows have only their metadata refreshed;
  weights and levels assigned by an admin via ``/admin/positions`` are not
  clobbered on re-runs.
- PMO members are synced per (pmo_id, employee_id) for the open membership
  only — closed memberships (``to_date IS NOT NULL``) are left alone.
"""

from __future__ import annotations

from datetime import date, timedelta

import structlog
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.department import Department
from app.models.employee import Employee
from app.models.level_threshold import LevelThreshold
from app.models.pmo import PMO, PMOMember
from app.models.position import Position
from app.models.reporting_relation import ReportingRelation

logger = structlog.get_logger()


# ── Reference data ────────────────────────────────────────────────────


LEVELS: list[dict] = [
    {"level_number": 1, "weight_from": 0,   "weight_to": 99,  "label": "Топ-менеджмент", "color": "#1e293b"},
    {"level_number": 2, "weight_from": 100, "weight_to": 199, "label": "Руководство",     "color": "#3b82f6"},
    {"level_number": 3, "weight_from": 200, "weight_to": 299, "label": "Менеджмент",      "color": "#10b981"},
    {"level_number": 4, "weight_from": 300, "weight_to": 399, "label": "Специалисты",     "color": "#f59e0b"},
    {"level_number": 5, "weight_from": 400, "weight_to": 499, "label": "Сотрудники",      "color": "#94a3b8"},
]

# Single root department holding all seeded positions. The chart no longer
# renders department nodes in `mode=positions` — they live here for foreign-
# key correctness only. Other dept-aware pages (Структура, lists) still see
# the unit.
DEPARTMENTS: list[dict] = [
    {"name": "Hi-Tech Group", "path": "hq", "unit_type": "headquarters", "description": "Головная организация"},
]

# Position titles must be globally unique. The two "phantom" positions
# (governance units with no holder) sit at the top.
POSITIONS: list[dict] = [
    # Phantoms — no employees attached. Drawn as group cards.
    {"title": "Board of Directors", "dept": "Hi-Tech Group", "weight": 5,  "level": 1, "grade": 10, "phantom": True},
    {"title": "Advisory Board",     "dept": "Hi-Tech Group", "weight": 105, "level": 2, "grade": 9,  "phantom": True},

    # CEO
    {"title": "CEO", "dept": "Hi-Tech Group", "weight": 10, "level": 1, "grade": 10},

    # Lateral directors under CEO
    {"title": "Staff Director",     "dept": "Hi-Tech Group", "weight": 110, "level": 2, "grade": 8},
    {"title": "Volunteer Director", "dept": "Hi-Tech Group", "weight": 120, "level": 2, "grade": 8},

    # Functional directors
    {"title": "Finance Director",        "dept": "Hi-Tech Group", "weight": 130, "level": 2, "grade": 8},
    {"title": "Communications Director", "dept": "Hi-Tech Group", "weight": 140, "level": 2, "grade": 8},
    {"title": "Fundraising Director",    "dept": "Hi-Tech Group", "weight": 150, "level": 2, "grade": 8},
    {"title": "Program Director",        "dept": "Hi-Tech Group", "weight": 160, "level": 2, "grade": 8},
    {"title": "Operations Director",     "dept": "Hi-Tech Group", "weight": 170, "level": 2, "grade": 8},

    # Specialists — pairs under each functional director. Titles disambiguated
    # via Senior/Junior so the global UNIQUE on title is satisfied.
    {"title": "Senior Finance Specialist",         "dept": "Hi-Tech Group", "weight": 210, "level": 3, "grade": 6},
    {"title": "Junior Finance Specialist",         "dept": "Hi-Tech Group", "weight": 215, "level": 3, "grade": 5},
    {"title": "Senior Communications Specialist",  "dept": "Hi-Tech Group", "weight": 220, "level": 3, "grade": 6},
    {"title": "Junior Communications Specialist",  "dept": "Hi-Tech Group", "weight": 225, "level": 3, "grade": 5},
    {"title": "Senior Fundraising Specialist",     "dept": "Hi-Tech Group", "weight": 230, "level": 3, "grade": 6},
    {"title": "Junior Fundraising Specialist",     "dept": "Hi-Tech Group", "weight": 235, "level": 3, "grade": 5},
    {"title": "Senior Program Specialist",         "dept": "Hi-Tech Group", "weight": 240, "level": 3, "grade": 6},
    {"title": "Junior Program Specialist",         "dept": "Hi-Tech Group", "weight": 245, "level": 3, "grade": 5},
    {"title": "Senior Operations Specialist",      "dept": "Hi-Tech Group", "weight": 250, "level": 3, "grade": 6},
    {"title": "Junior Operations Specialist",      "dept": "Hi-Tech Group", "weight": 255, "level": 3, "grade": 5},
]

# Employees mirror the names from the reference picture. Pravatar produces a
# stable real-photo avatar per email.
EMPLOYEES: list[dict] = [
    {"first_name": "Erica",     "last_name": "Romaguera",  "email": "erica.romaguera@hitech.demo",  "position": "CEO"},
    {"first_name": "Russell",   "last_name": "Ross",       "email": "russell.ross@hitech.demo",     "position": "Staff Director"},
    {"first_name": "David",     "last_name": "Sellner",    "email": "david.sellner@hitech.demo",    "position": "Volunteer Director"},
    {"first_name": "Bent",      "last_name": "Grasha",     "email": "bent.grasha@hitech.demo",      "position": "Finance Director"},
    {"first_name": "Debby",     "last_name": "Lethem",     "email": "debby.lethem@hitech.demo",     "position": "Communications Director"},
    {"first_name": "Brigida",   "last_name": "Withey",     "email": "brigida.withey@hitech.demo",   "position": "Fundraising Director"},
    {"first_name": "Mickey",    "last_name": "Neilands",   "email": "mickey.neilands@hitech.demo",  "position": "Program Director"},
    {"first_name": "Percy",     "last_name": "Veltman",    "email": "percy.veltman@hitech.demo",    "position": "Operations Director"},
    {"first_name": "Matteo",    "last_name": "Gobeaux",    "email": "matteo.gobeaux@hitech.demo",   "position": "Senior Finance Specialist"},
    {"first_name": "Berkley",   "last_name": "Esherwood",  "email": "berkley.esherwood@hitech.demo","position": "Junior Finance Specialist"},
    {"first_name": "Bernadine", "last_name": "Godsell",    "email": "bernadine.godsell@hitech.demo","position": "Senior Communications Specialist"},
    {"first_name": "Gianni",    "last_name": "Block",      "email": "gianni.block@hitech.demo",     "position": "Junior Communications Specialist"},
    {"first_name": "Birgitta",  "last_name": "Rosoni",     "email": "birgitta.rosoni@hitech.demo",  "position": "Senior Fundraising Specialist"},
    {"first_name": "Dorena",    "last_name": "Whebell",    "email": "dorena.whebell@hitech.demo",   "position": "Junior Fundraising Specialist"},
    {"first_name": "Caleigh",   "last_name": "Jerde",      "email": "caleigh.jerde@hitech.demo",    "position": "Senior Program Specialist"},
    {"first_name": "Laney",     "last_name": "Christmas",  "email": "laney.christmas@hitech.demo",  "position": "Junior Program Specialist"},
    {"first_name": "Bartholemy","last_name": "Durgan",     "email": "bartholemy.durgan@hitech.demo","position": "Senior Operations Specialist"},
    {"first_name": "Bernelle",  "last_name": "Cubley",     "email": "bernelle.cubley@hitech.demo",  "position": "Junior Operations Specialist"},
]

# Pravatar gives a deterministic photo per `u=` seed.
def _avatar_url(email: str) -> str:
    return f"https://i.pravatar.cc/150?u={email}"


# Position-to-position reporting hierarchy (matches the reference picture).
REPORTING_RELATIONS: list[tuple[str, str]] = [
    # Top of the tree
    ("Board of Directors", "CEO"),
    # CEO's direct reports
    ("CEO", "Advisory Board"),
    ("CEO", "Staff Director"),
    ("CEO", "Volunteer Director"),
    ("CEO", "Finance Director"),
    ("CEO", "Communications Director"),
    ("CEO", "Fundraising Director"),
    ("CEO", "Program Director"),
    ("CEO", "Operations Director"),
    # Each functional director → two specialists
    ("Finance Director",        "Senior Finance Specialist"),
    ("Finance Director",        "Junior Finance Specialist"),
    ("Communications Director", "Senior Communications Specialist"),
    ("Communications Director", "Junior Communications Specialist"),
    ("Fundraising Director",    "Senior Fundraising Specialist"),
    ("Fundraising Director",    "Junior Fundraising Specialist"),
    ("Program Director",        "Senior Program Specialist"),
    ("Program Director",        "Junior Program Specialist"),
    ("Operations Director",     "Senior Operations Specialist"),
    ("Operations Director",     "Junior Operations Specialist"),
]

# CEO is the manager of the root department for completeness.
DEPARTMENT_MANAGERS: dict[str, str] = {
    "Hi-Tech Group": "erica.romaguera@hitech.demo",
}

# membership_type ∈ {permanent, assigned, consulting} per the model's CheckConstraint.
PMOS: list[dict] = [
    {
        "code": "PMO-DIGITAL",
        "name": "Digital Transformation",
        "description": "Modernisation of internal systems",
        "head_email": "percy.veltman@hitech.demo",
        "members": [
            {"email": "percy.veltman@hitech.demo",   "type": "permanent",  "alloc": 50, "primary": True,  "role": "Programme Director"},
            {"email": "erica.romaguera@hitech.demo", "type": "consulting", "alloc": 20, "primary": False, "role": "Sponsor"},
            {"email": "matteo.gobeaux@hitech.demo",  "type": "assigned",   "alloc": 60, "primary": False, "role": "Solution architect"},
            {"email": "caleigh.jerde@hitech.demo",   "type": "assigned",   "alloc": 50, "primary": False, "role": "Programme analyst"},
        ],
    },
    {
        "code": "PMO-RECRUIT",
        "name": "Mass hiring 2026",
        "description": "30 hires per quarter pipeline",
        "head_email": "russell.ross@hitech.demo",
        "members": [
            {"email": "russell.ross@hitech.demo",     "type": "permanent",  "alloc": 80, "primary": True,  "role": "Programme curator"},
            {"email": "david.sellner@hitech.demo",    "type": "assigned",   "alloc": 60, "primary": False, "role": "Volunteer interviewer"},
            # Bent gives an over-allocation: 100 in BRAND + … no, we'll let Erica trip the warning.
            {"email": "bent.grasha@hitech.demo",      "type": "consulting", "alloc": 30, "primary": False, "role": "Budget reviewer"},
            {"email": "erica.romaguera@hitech.demo",  "type": "consulting", "alloc": 30, "primary": False, "role": "Sponsor"},
        ],
    },
    {
        "code": "PMO-BRAND",
        "name": "Rebranding",
        "description": "Visual identity and website refresh",
        "head_email": "debby.lethem@hitech.demo",
        "members": [
            {"email": "debby.lethem@hitech.demo",      "type": "permanent",  "alloc": 70, "primary": True,  "role": "Curator"},
            {"email": "bernadine.godsell@hitech.demo", "type": "assigned",   "alloc": 90, "primary": False, "role": "Lead designer"},
            {"email": "erica.romaguera@hitech.demo",  "type": "consulting", "alloc": 60, "primary": False, "role": "Sponsor"},
            # Erica total: 20 + 30 + 60 = 110% — UI shows the allocation warning.
        ],
    },
]


DEMO_EMAIL_SUFFIX = "@hitech.demo"
DEMO_PMO_CODES = tuple(p["code"] for p in PMOS)


# Static lists of historical seed identifiers, used by ``reset_demo_data`` to
# wipe rows produced by older versions of this seeder. Append here when the
# canonical seed shape changes; do not delete entries.
LEGACY_DEPARTMENT_NAMES: tuple[str, ...] = (
    # Original 2026-Q1 seed (Russian, dept-rich)
    "IT-департамент", "Backend-команда", "Frontend-команда",
    "HR-департамент", "Финансовый отдел", "Маркетинг",
)
LEGACY_POSITION_TITLES: tuple[str, ...] = (
    "Генеральный директор", "Финансовый директор",
    "Руководитель IT", "Руководитель HR", "Руководитель маркетинга",
    "Главный бухгалтер", "Тимлид Backend", "Тимлид Frontend", "HR-менеджер",
    "Senior Backend Engineer", "Senior Frontend Engineer",
    "Маркетинг-аналитик", "Бухгалтер",
    "Junior Backend Engineer", "Junior Frontend Engineer", "Стажёр",
)


# ── Public API ────────────────────────────────────────────────────────


async def is_demo_data_present(session: AsyncSession) -> bool:
    """Cheap probe: does at least one synthetic demo employee exist?"""
    n = (
        await session.execute(
            select(func.count(Employee.id)).where(
                Employee.email.like(f"%{DEMO_EMAIL_SUFFIX}")
            )
        )
    ).scalar() or 0
    return n > 0


async def seed_demo_data(session: AsyncSession, *, force: bool = False) -> dict:
    """Seed demo HR data. Returns a counts dict.

    By default this is a no-op when a previous seed is detected
    (``is_demo_data_present()`` is True). Pass ``force=True`` to upsert
    over an existing seed. Real (non-demo) rows are never touched.

    The caller is responsible for committing the session — this function
    only flushes.
    """
    if not force and await is_demo_data_present(session):
        logger.info("demo_seed_skipped", reason="already_present")
        return {"status": "skipped"}

    await _backfill_level_colors(session)
    depts = await _upsert_departments(session)
    positions = await _upsert_positions(session, depts)
    employees = await _upsert_employees(session, positions)
    await _attach_department_managers(session, depts, employees)
    rel_count = await _upsert_reporting_relations(session, positions)
    pmo_count = await _upsert_pmos(session, employees)

    counts = {
        "status": "seeded",
        "levels": len(LEVELS),
        "departments": len(DEPARTMENTS),
        "positions": len(POSITIONS),
        "employees": len(EMPLOYEES),
        "reporting_relations": rel_count,
        "pmos": pmo_count,
    }
    logger.info("demo_seed_completed", **counts)
    return counts


async def reset_demo_data(session: AsyncSession) -> None:
    """Delete only seed-tagged rows — current seed *and* any historical seeds.

    Identifies demo rows by:
    - ``Employee.email`` ending in ``@hitech.demo``;
    - ``PMO.code`` in the seed list;
    - ``Position.title`` matching the current or any legacy seed title;
    - ``Department.name`` matching the current or any legacy seed name.
    """
    logger.info("demo_seed_reset_started")

    # PMO members + PMOs
    await session.execute(
        text(
            "DELETE FROM hr_pmo_members WHERE employee_id IN ("
            "SELECT id FROM hr_employees WHERE email LIKE :pattern)"
        ),
        {"pattern": f"%{DEMO_EMAIL_SUFFIX}"},
    )
    await session.execute(
        text("DELETE FROM hr_pmos WHERE code = ANY(:codes)"),
        {"codes": list(DEMO_PMO_CODES)},
    )

    seed_titles = list({*(p["title"] for p in POSITIONS), *LEGACY_POSITION_TITLES})

    # Reporting relations referencing seed positions (old or new)
    await session.execute(
        text(
            "DELETE FROM hr_reporting_relations "
            "WHERE superior_position_id IN (SELECT id FROM hr_positions WHERE title = ANY(:titles)) "
            "   OR subordinate_position_id IN (SELECT id FROM hr_positions WHERE title = ANY(:titles))"
        ),
        {"titles": seed_titles},
    )

    # NULL out manager FK on demo departments before deleting employees.
    await session.execute(
        text(
            "UPDATE hr_departments SET manager_id = NULL "
            "WHERE manager_id IN ("
            "SELECT id FROM hr_employees WHERE email LIKE :pattern)"
        ),
        {"pattern": f"%{DEMO_EMAIL_SUFFIX}"},
    )
    await session.execute(
        text("DELETE FROM hr_employees WHERE email LIKE :pattern"),
        {"pattern": f"%{DEMO_EMAIL_SUFFIX}"},
    )
    await session.execute(
        text("DELETE FROM hr_positions WHERE title = ANY(:titles)"),
        {"titles": seed_titles},
    )
    seed_dept_names = list({*(d["name"] for d in DEPARTMENTS), *LEGACY_DEPARTMENT_NAMES})
    await session.execute(
        text("DELETE FROM hr_departments WHERE name = ANY(:names)"),
        {"names": seed_dept_names},
    )
    await session.flush()
    logger.info("demo_seed_reset_done")


# ── Internal upsert helpers ───────────────────────────────────────────


async def _backfill_level_colors(session: AsyncSession) -> None:
    """Set colour for any LevelThreshold row that doesn't yet have one."""
    rows = (await session.execute(select(LevelThreshold))).scalars().all()
    by_number = {lt.level_number: lt for lt in rows}
    for spec in LEVELS:
        lt = by_number.get(spec["level_number"])
        if lt is None:
            session.add(LevelThreshold(**spec))
        elif lt.color is None:
            lt.color = spec["color"]
            if not lt.label:
                lt.label = spec["label"]
    await session.flush()


async def _upsert_departments(session: AsyncSession) -> dict[str, Department]:
    existing = {
        d.path: d
        for d in (await session.execute(select(Department))).scalars().all()
    }
    name_to_dept: dict[str, Department] = {d.name: d for d in existing.values()}
    for spec in DEPARTMENTS:
        d = existing.get(spec["path"])
        if d is None:
            d = Department(
                name=spec["name"],
                path=spec["path"],
                unit_type=spec["unit_type"],
                description=spec["description"],
                is_active=True,
            )
            session.add(d)
        else:
            d.name = spec["name"]
            d.unit_type = spec["unit_type"]
            d.description = spec["description"]
        name_to_dept[spec["name"]] = d
    await session.flush()
    return name_to_dept


async def _upsert_positions(
    session: AsyncSession, depts: dict[str, Department]
) -> dict[str, Position]:
    existing = {
        p.title: p
        for p in (await session.execute(select(Position))).scalars().all()
    }
    out: dict[str, Position] = {}
    for spec in POSITIONS:
        dept = depts[spec["dept"]]
        p = existing.get(spec["title"])
        if p is None:
            p = Position(
                title=spec["title"],
                department_id=dept.id,
                weight=spec["weight"],
                level=spec["level"],
                grade=spec["grade"],
                is_active=True,
            )
            session.add(p)
        else:
            # Don't overwrite weight/level once set by an admin via the UI.
            p.department_id = dept.id
            p.grade = spec["grade"]
            p.is_active = True
        out[spec["title"]] = p
    await session.flush()
    return out


async def _upsert_employees(
    session: AsyncSession, positions: dict[str, Position]
) -> dict[str, Employee]:
    existing = {
        e.email: e
        for e in (await session.execute(select(Employee))).scalars().all()
    }
    today = date.today()
    out: dict[str, Employee] = {}
    for spec in EMPLOYEES:
        position = positions[spec["position"]]
        avatar = _avatar_url(spec["email"])
        e = existing.get(spec["email"])
        if e is None:
            e = Employee(
                first_name=spec["first_name"],
                last_name=spec["last_name"],
                email=spec["email"],
                department_id=position.department_id,
                position_id=position.id,
                hire_date=today - timedelta(days=400),
                status="active",
                avatar_url=avatar,
            )
            session.add(e)
        else:
            e.first_name = spec["first_name"]
            e.last_name = spec["last_name"]
            e.department_id = position.department_id
            e.position_id = position.id
            e.status = "active"
            e.is_deleted = False
            if not e.avatar_url:
                e.avatar_url = avatar
        out[spec["email"]] = e
    await session.flush()
    return out


async def _attach_department_managers(
    session: AsyncSession,
    depts: dict[str, Department],
    employees: dict[str, Employee],
) -> None:
    for dept_name, email in DEPARTMENT_MANAGERS.items():
        d = depts.get(dept_name)
        e = employees.get(email)
        if d and e:
            d.manager_id = e.id
    await session.flush()


async def _upsert_reporting_relations(
    session: AsyncSession, positions: dict[str, Position]
) -> int:
    """Idempotently install the demo reporting hierarchy.

    Re-uses existing rows when (superior, subordinate, relation_type) already
    matches; otherwise inserts. Doesn't delete extras the user may have added
    manually via the UI.
    """
    existing = (await session.execute(select(ReportingRelation))).scalars().all()
    by_pair = {
        (r.superior_position_id, r.subordinate_position_id, r.relation_type): r
        for r in existing
    }
    today = date.today()
    inserted = 0
    for sup_title, sub_title in REPORTING_RELATIONS:
        sup = positions.get(sup_title)
        sub = positions.get(sub_title)
        if sup is None or sub is None:
            continue
        key = (sup.id, sub.id, "direct")
        if key in by_pair:
            continue
        session.add(
            ReportingRelation(
                superior_position_id=sup.id,
                subordinate_position_id=sub.id,
                relation_type="direct",
                effective_from=today,
                effective_to=None,
            )
        )
        inserted += 1
    await session.flush()
    return inserted


async def _upsert_pmos(
    session: AsyncSession, employees: dict[str, Employee]
) -> int:
    today = date.today()
    existing = {p.code: p for p in (await session.execute(select(PMO))).scalars().all()}
    seeded = 0
    for spec in PMOS:
        head = employees.get(spec["head_email"])
        head_id = head.id if head else None
        pmo = existing.get(spec["code"])
        if pmo is None:
            pmo = PMO(
                code=spec["code"],
                name=spec["name"],
                description=spec["description"],
                head_employee_id=head_id,
                status="active",
            )
            session.add(pmo)
            await session.flush()
        else:
            pmo.name = spec["name"]
            pmo.description = spec["description"]
            pmo.head_employee_id = head_id
            pmo.status = "active"

        open_members = (
            await session.execute(
                select(PMOMember).where(
                    PMOMember.pmo_id == pmo.id,
                    PMOMember.to_date.is_(None),
                )
            )
        ).scalars().all()
        by_emp = {m.employee_id: m for m in open_members}

        wants_primary_emp_id: int | None = None
        for ms in spec["members"]:
            if ms.get("primary"):
                emp = employees.get(ms["email"])
                if emp:
                    wants_primary_emp_id = emp.id
                break
        if wants_primary_emp_id is not None:
            for m in open_members:
                if m.is_primary and m.employee_id != wants_primary_emp_id:
                    m.is_primary = False
            await session.flush()

        for ms in spec["members"]:
            emp = employees.get(ms["email"])
            if emp is None:
                continue
            m = by_emp.get(emp.id)
            if m is None:
                session.add(
                    PMOMember(
                        pmo_id=pmo.id,
                        employee_id=emp.id,
                        membership_type=ms["type"],
                        position_in_pmo=ms.get("role"),
                        from_date=today - timedelta(days=30),
                        to_date=None,
                        allocation_percent=ms["alloc"],
                        is_primary=bool(ms.get("primary")),
                    )
                )
            else:
                m.membership_type = ms["type"]
                m.position_in_pmo = ms.get("role")
                m.allocation_percent = ms["alloc"]
                m.is_primary = bool(ms.get("primary"))
        await session.flush()
        seeded += 1
    return seeded
