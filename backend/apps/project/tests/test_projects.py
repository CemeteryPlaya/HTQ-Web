"""Проект: руководитель — участник автоматически, архив не ищется (§18, Q-E26)."""

import pytest

from apps.project import interface
from apps.project.models import Project, ProjectStatus
from apps.project.services import projects


def _make(**over):
    fields = {"code": "П-015", "name": "Объект 15", "country_code": "KZ",
              "manager_user_id": 11, "actor_id": 1}
    fields.update(over)
    return projects.create(**fields)


@pytest.mark.django_db
def test_manager_becomes_a_member(company_context):
    project = _make()
    assert interface.is_member(str(project.id), 11)
    assert interface.member_project_ids(11) == [str(project.id)]


@pytest.mark.django_db
def test_changing_manager_adds_the_new_one(company_context):
    project = _make()
    projects.update(project, manager_user_id=12, actor_id=1)
    assert interface.is_member(str(project.id), 12)
    assert interface.is_member(str(project.id), 11)  # прежний остаётся участником


@pytest.mark.django_db
def test_manager_cannot_be_removed_while_manager(company_context):
    project = _make()
    with pytest.raises(projects.ProjectError):
        projects.remove_member(project, 11, actor_id=1)


@pytest.mark.django_db
def test_code_is_unique(company_context):
    _make()
    with pytest.raises(projects.ProjectError):
        _make(name="Другой")


@pytest.mark.django_db
def test_search_hides_archive_and_respects_membership(company_context):
    mine = _make()
    other = _make(code="П-016", name="Объект 16", manager_user_id=12)
    archived = _make(code="П-017", name="Объект 17")
    projects.update(archived, status=ProjectStatus.ARCHIVED, actor_id=1)
    found = interface.search_projects("Объект", user_id=11, only_member=False)
    assert {row["code"] for row in found} == {"П-015", "П-016"}
    only_mine = interface.search_projects("Объект", user_id=11, only_member=True)
    assert [row["id"] for row in only_mine] == [str(mine.id)]
    assert interface.project_brief([str(other.id)])[str(other.id)]["manager_user_id"] == 12


@pytest.mark.django_db
def test_company_overhead_kind(company_context):
    overhead = _make(code="ОБЩ", name="Общие расходы компании", kind="company_overhead")
    assert Project.objects.get(pk=overhead.pk).kind == "company_overhead"


@pytest.mark.django_db
def test_member_user_ids_are_manager_and_members(company_context):
    """Получатели уведомлений по проекту (ТЗ §16.2 п.1): руководитель плюс
    участники, без повторов; чужой или неверный ключ — пусто."""
    project = _make()
    projects.add_member(project, 31, actor_id=1)
    projects.add_member(project, 22, actor_id=1)
    assert interface.member_user_ids(str(project.id)) == [11, 22, 31]
    other = _make(code="П-016", manager_user_id=None)
    assert interface.member_user_ids(str(other.id)) == []
    assert interface.member_user_ids("00000000-0000-0000-0000-000000000000") == []
    assert interface.member_user_ids("не-uuid") == []
