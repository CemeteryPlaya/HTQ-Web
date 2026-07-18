"""sqladmin ModelViews for hr-service.

Consolidated for brevity — split into per-model files under views/ if any
ModelView grows beyond a few lines of customisation.
"""

from sqladmin import ModelView

from app.models.application import Application
from app.models.audit_log import AuditLog
from app.models.department import Department
from app.models.document import Document
from app.models.employee import Employee
from app.models.level_threshold import LevelThreshold
from app.models.org_settings import OrgSettings
from app.models.pmo import PMO
from app.models.position import Position
from app.models.reporting_relation import ReportingRelation
from app.models.shareable_link import ShareableLink
from app.models.time_tracking import TimeEntry
from app.models.vacancy import Vacancy


class EmployeeAdmin(ModelView, model=Employee):
    name_plural = "Employees"
    icon = "fa-solid fa-id-badge"
    column_list = ["id", "first_name", "last_name", "email", "department_id", "position_id", "status"]
    column_searchable_list = ["first_name", "last_name", "email"]
    column_sortable_list = ["id", "last_name", "hire_date", "status"]


class DepartmentAdmin(ModelView, model=Department):
    name_plural = "Departments"
    icon = "fa-solid fa-sitemap"
    column_list = ["id", "name", "path", "unit_type", "manager_id", "is_active"]
    column_searchable_list = ["name", "path"]


class PositionAdmin(ModelView, model=Position):
    name_plural = "Positions"
    icon = "fa-solid fa-briefcase"
    column_list = ["id", "title", "department_id", "grade", "weight", "level"]
    column_searchable_list = ["title"]


class VacancyAdmin(ModelView, model=Vacancy):
    name_plural = "Vacancies"
    icon = "fa-solid fa-bullhorn"
    column_list = ["id", "title", "department_id", "position_id", "status", "opened_at"]
    column_searchable_list = ["title"]


class ApplicationAdmin(ModelView, model=Application):
    name_plural = "Applications"
    icon = "fa-solid fa-file-signature"
    column_list = ["id", "vacancy_id", "candidate_name", "candidate_email", "status", "applied_at"]
    column_searchable_list = ["candidate_name", "candidate_email"]


class TimeEntryAdmin(ModelView, model=TimeEntry):
    name_plural = "Time entries"
    icon = "fa-solid fa-clock"
    column_list = ["id", "employee_id", "date", "start_time", "end_time", "project"]
    column_sortable_list = ["date", "employee_id"]


class DocumentAdmin(ModelView, model=Document):
    name_plural = "Documents"
    icon = "fa-solid fa-file-lines"
    column_list = ["id", "employee_id", "title", "doc_type", "uploaded_by", "created_at"]
    column_searchable_list = ["title"]


class AuditLogAdmin(ModelView, model=AuditLog):
    name_plural = "Audit log"
    icon = "fa-solid fa-list-check"
    column_list = ["id", "changed_by", "action", "entity_type", "entity_id", "created_at"]
    column_default_sort = [("created_at", True)]
    can_create = False
    can_edit = False
    can_delete = False


class OrgSettingsAdmin(ModelView, model=OrgSettings):
    name_plural = "Org settings"
    icon = "fa-solid fa-gear"
    column_list = ["id", "key", "value", "updated_at"]
    column_searchable_list = ["key"]


class PMOAssignmentAdmin(ModelView, model=PMO):
    name = "PMO"
    name_plural = "PMOs"
    icon = "fa-solid fa-diagram-project"
    column_list = ["id", "code", "name", "status", "head_employee_id"]
    column_searchable_list = ["code", "name"]


class ReportingRelationAdmin(ModelView, model=ReportingRelation):
    name_plural = "Reporting relations"
    icon = "fa-solid fa-arrow-up-right-dots"
    column_list = [
        "id",
        "superior_position_id",
        "subordinate_position_id",
        "relation_type",
        "effective_from",
        "effective_to",
    ]


class ShareableLinkAdmin(ModelView, model=ShareableLink):
    name_plural = "Shareable links"
    icon = "fa-solid fa-link"
    column_list = ["id", "label", "link_type", "is_active", "expires_at", "created_at"]


class LevelThresholdAdmin(ModelView, model=LevelThreshold):
    name_plural = "Level thresholds"
    icon = "fa-solid fa-layer-group"
    column_list = ["id", "level_number", "weight_from", "weight_to", "label"]
