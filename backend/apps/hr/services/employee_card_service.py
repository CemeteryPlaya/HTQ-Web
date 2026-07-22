"""EmployeeCardService.build_card — сборка полной карточки сотрудника —
порт services/hr/app/services/employee_card_service.py.

Функция, а не класс (та же конвенция порта, что department_service.py/
pmo_service.py/… — исходник был class-based только из-за DI асинхронной
SQLAlchemy-сессии, здесь синхронный Django ORM без сессии).

Карточка агрегирует всё, что должен видеть смотрящий на странице
``/hr/employees/:id``: базовую идентификацию, контакты, должность, отдел,
руководителя, прямых подчинённых и активные PMO-членства.

Два режима:
- ``mode="full"``  — полная HR-карточка (``employees.py::my_employee_card``/
  ``employee_card`` — оба РАСКРЫТЫ этим под-модулем). Секция ``t2`` (Т-2
  скалярные поля с полевым RBAC-гейтингом) подмешивается ТОЛЬКО когда
  вызывающий передал ``access`` — буквальный порт условия исходника
  (``if mode == "full" and access is not None``).
- ``mode="public"`` — публичная share-link карточка. Контракт режима
  (глушит email/phone) переносится буквально, но ни один вызывающий код
  этого под-модуля им не пользуется — ``PublicEmployeeView``/share-links
  остаются задачей своего отдельного брифа.

``manager``/``subordinates`` — та же эвристика исходника: руководителем
считается ``Department.manager`` отдела сотрудника; если сотрудник сам
руководитель своего отдела (или у отдела нет руководителя), поднимаемся по
``path`` вверх до первого отдела с руководителем, отличным от самого
сотрудника. ``subordinates`` — прямые (НЕ по всему поддереву) активные
сотрудники отделов, у которых ``manager_id == emp.id`` — буквальный порт
докстринга исходника (`_resolve_subordinates`), включая его собственное
предупреждение о том, что вложенные подчинённые сюда не попадают.
"""
from __future__ import annotations

from apps.hr.models import Department, Employee
from apps.hr.services import employee_service as emp_svc
from apps.hr.services import pmo_service as pmo_svc


def _full_name(emp: Employee) -> str:
    parts = [emp.last_name or "", emp.first_name or "", emp.middle_name or ""]
    return " ".join(p for p in parts if p).strip()


def _employee_brief(emp: Employee, *, with_contacts: bool) -> dict:
    out: dict = {
        "id": emp.id,
        "full_name": _full_name(emp),
        "first_name": emp.first_name,
        "last_name": emp.last_name,
        "middle_name": emp.middle_name,
        "avatar_url": emp.avatar_url,
        "position_title": emp.position.title if emp.position_id else None,
        "department_name": emp.department.name if emp.department_id else None,
        "status": emp.status,
    }
    if with_contacts:
        out["email"] = emp.email
        out["phone"] = emp.phone
    return out


def _climb_to_parent_manager(emp: Employee) -> Employee | None:
    """Walk the path upwards until a department with a (non-self) head."""
    if not emp.department_id:
        return None
    path_parts = emp.department.path.split(".")
    while len(path_parts) > 1:
        path_parts = path_parts[:-1]
        parent_path = ".".join(path_parts)
        parent = Department.objects.filter(path=parent_path).first()
        if parent is not None and parent.manager_id and parent.manager_id != emp.id:
            return (
                Employee.objects.select_related("department", "position")
                .filter(id=parent.manager_id)
                .first()
            )
    return None


def _resolve_manager(emp: Employee) -> Employee | None:
    if not emp.department_id or not emp.department.manager_id:
        return _climb_to_parent_manager(emp)
    if emp.department.manager_id == emp.id:
        return _climb_to_parent_manager(emp)
    return (
        Employee.objects.select_related("department", "position")
        .filter(id=emp.department.manager_id)
        .first()
    )


def _resolve_subordinates(emp: Employee) -> list[Employee]:
    dept_ids = list(
        Department.objects.filter(manager_id=emp.id, is_active=True).values_list("id", flat=True)
    )
    if not dept_ids:
        return []
    return list(
        Employee.objects.filter(department_id__in=dept_ids, is_deleted=False, status="active")
        .exclude(id=emp.id)
        .select_related("department", "position")
        .order_by("last_name")
    )


def build_card(employee_id: int, *, mode: str = "full", access=None) -> dict:
    """``emp_svc.get_employee`` уже воспроизводит ``_load_employee`` исходника
    буквально (та же фильтрация ``is_deleted=False`` + ``select_related``
    department/position) — повторно её здесь не определяем, поднимает
    ``emp_svc.EmployeeNotFound`` (вьюха превращает в 404 ровно как везде)."""
    emp = emp_svc.get_employee(employee_id)

    manager = _resolve_manager(emp)
    subordinates = _resolve_subordinates(emp)
    pmos = pmo_svc.get_employee_pmos(emp.id)
    with_contacts = mode == "full"

    card: dict = {
        "id": emp.id,
        "user_id": emp.user_id,
        "first_name": emp.first_name,
        "last_name": emp.last_name,
        "middle_name": emp.middle_name,
        "full_name": _full_name(emp),
        "avatar_url": emp.avatar_url,
        "bio": emp.bio,
        "status": emp.status,
        "hire_date": emp.hire_date.isoformat() if emp.hire_date else None,
        "termination_date": (
            emp.termination_date.isoformat() if emp.termination_date else None
        ),
        "department": (
            {"id": emp.department.id, "name": emp.department.name, "path": emp.department.path}
            if emp.department_id
            else None
        ),
        "position": (
            {
                "id": emp.position.id,
                "title": emp.position.title,
                "grade": emp.position.grade,
                "level": emp.position.level,
            }
            if emp.position_id
            else None
        ),
        "manager": (
            _employee_brief(manager, with_contacts=with_contacts) if manager else None
        ),
        "subordinates": [
            _employee_brief(sub, with_contacts=with_contacts) for sub in subordinates
        ],
        "pmos": pmos,
    }

    if mode == "full":
        card["email"] = emp.email
        card["phone"] = emp.phone
    else:
        # Belt-and-braces: never let PII leak to a public-link consumer even
        # if the caller forgets to strip it on the route layer.
        card["email"] = None
        card["phone"] = None

    if mode == "full" and access is not None:
        from apps.hr.services import employee_card_t2_service as t2_svc

        card["t2"] = t2_svc.read_sections(emp.id, access)
    else:
        card["t2"] = {}

    return card
