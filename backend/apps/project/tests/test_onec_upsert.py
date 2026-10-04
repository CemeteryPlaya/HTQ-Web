"""Заготовка 1С: идемпотентный upsert «Проектов» (A7.3, D-38, D-S7-5).

Сопоставление — по ``ext_1c_ref``, затем по коду проекта.
"""

from __future__ import annotations

import re

import pytest
from django.db import IntegrityError, transaction

from apps.project import interface
from apps.project.models import Project
from apps.project.services import onec, projects
from htqweb.tenancy.db import use_company

GUID_A = "0f8fad5b-d9cb-469f-a165-70867728950e"
GUID_B = "7c9e6679-7425-40de-944b-e07fc1f90ae7"


def _countries() -> None:
    from apps.refdata.models import Country

    Country.objects.get_or_create(code="KZ", defaults={"name": "Казахстан"})


@pytest.fixture
def ctx(two_company_schemas):
    _countries()
    with use_company(two_company_schemas[0]):
        yield two_company_schemas


def _record(code: str = "П-015", guid: str = GUID_A, **over) -> dict:
    row = {"Ref_Key": guid, "Code": code, "Description": "Объект 15", "КодСтраны": "KZ"}
    row.update(over)
    return row


def test_new_record_is_created_with_ref(ctx):
    out = onec.upsert_project(_record())
    project = Project.objects.get(pk=out.object_id)
    assert out.status == "created" and project.ext_1c_ref == GUID_A and project.code == "П-015"
    assert project.created_by is None


def test_repeat_is_unchanged(ctx):
    onec.upsert_project(_record())
    again = onec.upsert_project(_record())
    assert again.status == "unchanged" and Project.objects.count() == 1


def test_changed_name_is_updated_by_ref(ctx):
    onec.upsert_project(_record())
    out = onec.upsert_project(_record(Description="Объект 15 (новый этап)"))
    assert out.status == "updated"
    assert Project.objects.get().name == "Объект 15 (новый этап)"


def test_existing_project_without_ref_is_linked_by_code_keeping_its_name(ctx):
    mine = projects.create(code="П-015", name="Наше имя", country_code="KZ", actor_id=1)
    out = onec.upsert_project(_record(Description="Имя из 1С"))
    mine.refresh_from_db()
    assert out.status == "updated" and mine.ext_1c_ref == GUID_A and mine.name == "Наше имя"


def test_other_ref_on_the_same_code_is_a_conflict(ctx):
    mine = projects.create(code="П-015", name="Наше", country_code="KZ", actor_id=1,
                           ext_1c_ref=GUID_B)
    out = onec.upsert_project(_record())
    mine.refresh_from_db()
    assert out.status == "conflict" and mine.ext_1c_ref == GUID_B and mine.name == "Наше"


def test_code_change_of_a_linked_project_is_rejected(ctx):
    onec.upsert_project(_record())
    out = onec.upsert_project(_record(code="П-099"))
    assert out.status == "rejected" and Project.objects.get().code == "П-015"


def test_bad_guid_or_empty_code_is_rejected(ctx):
    assert onec.upsert_project(_record(guid="x")).status == "rejected"
    assert onec.upsert_project(_record(code="")).status == "rejected"
    assert Project.objects.count() == 0


def test_unknown_country_and_long_value_are_rejected(ctx):
    assert onec.upsert_project(_record(КодСтраны="ZZ")).status == "rejected"
    assert onec.upsert_project(_record(code="К" * 100)).status == "rejected"
    assert Project.objects.count() == 0


def test_interface_exposes_the_upsert(ctx):
    assert interface.upsert_project_from_1c(_record()).status == "created"


# ── ограничение уникальности ────────────────────────────────────────────

def test_duplicate_nonempty_ref_is_integrity_error(ctx):
    projects.create(code="П-1", name="a", country_code="KZ", actor_id=1, ext_1c_ref=GUID_A)
    with pytest.raises(IntegrityError), transaction.atomic():
        Project.objects.create(code="П-2", name="b", country_code="KZ", ext_1c_ref=GUID_A)


def test_several_empty_refs_are_allowed(ctx):
    projects.create(code="П-1", name="a", country_code="KZ", actor_id=1)
    projects.create(code="П-2", name="b", country_code="KZ", actor_id=1)
    assert Project.objects.filter(ext_1c_ref="").count() == 2


def test_same_ref_in_two_companies_is_allowed(two_company_schemas):
    _countries()
    for slug in two_company_schemas:
        with use_company(slug):
            assert onec.upsert_project(_record()).status == "created"


def test_brief_exposes_ext_1c_ref_and_update_rejects_taken_code(ctx):
    first = projects.create(code="П-1", name="a", country_code="KZ", actor_id=1, ext_1c_ref=GUID_A)
    other = projects.create(code="П-2", name="b", country_code="KZ", actor_id=1)
    assert projects.brief(first)["ext_1c_ref"] == GUID_A
    with pytest.raises(projects.ProjectError):
        projects.update(other, actor_id=1, ext_1c_ref=GUID_A)


def test_null_ref_clears_it_and_bad_ref_is_refused(ctx):
    project = projects.create(code="П-1", name="a", country_code="KZ", actor_id=1,
                              ext_1c_ref=GUID_A.upper())
    assert project.ext_1c_ref == GUID_A
    projects.update(project, actor_id=1, ext_1c_ref=None)
    project.refresh_from_db()
    assert project.ext_1c_ref == ""
    with pytest.raises(projects.ProjectError):
        projects.update(project, actor_id=1, ext_1c_ref="не-guid")


def test_taken_ref_on_create_is_not_reported_as_taken_code(ctx):
    projects.create(code="П-1", name="a", country_code="KZ", actor_id=1, ext_1c_ref=GUID_A)
    with pytest.raises(projects.ProjectError) as exc:
        projects.create(code="П-2", name="b", country_code="KZ", actor_id=1, ext_1c_ref=GUID_A)
    assert "Код в 1С" in str(exc.value)


def test_api_taken_ref_is_422_and_null_patch_is_ok(ctx):
    import json

    from django.test import Client

    from apps.access.tests.helpers import assign, token

    slug = ctx[0]
    assign(slug, 7, "project.projects", "full")
    assign(slug, 7, "project.all", "full")
    headers = {"HTTP_AUTHORIZATION": f"Bearer {token(user_id=7, sub='7', company=slug)}",
               "HTTP_X_HTQ_COMPANY": slug}
    client = Client()

    def call(method, url, body):
        return getattr(client, method)(f"/api/project/v1{url}", data=json.dumps(body),
                                       content_type="application/json", **headers)

    base = {"name": "Объект", "country_code": "KZ", "ext_1c_ref": GUID_A}
    first = call("post", "/projects", {**base, "code": "П-1"})
    assert first.status_code == 201 and first.json()["ext_1c_ref"] == GUID_A
    assert call("post", "/projects", {**base, "code": "П-2"}).status_code == 422
    other = call("post", "/projects", {**base, "code": "П-3", "ext_1c_ref": ""}).json()
    assert call("patch", f"/projects/{other['id']}", {"ext_1c_ref": GUID_A}).status_code == 422
    assert call("patch", f"/projects/{first.json()['id']}", {"ext_1c_ref": None}).status_code == 200


# ── только нижний регистр (D-S8-4) ──────────────────────────────────────

def test_uppercase_ref_past_the_service_is_integrity_error(ctx):
    """Мимо сервиса (ORM, django-admin, ручной SQL) верхний регистр в БД не
    попадает: иначе регистрозависимая уникальность пропустила бы второй
    экземпляр того же GUID."""
    with pytest.raises(IntegrityError, match="ck_project_ext_1c_lower"), transaction.atomic():
        Project.objects.create(code="П-1", name="a", country_code="KZ",
                               ext_1c_ref=GUID_A.upper())
    project = projects.create(code="П-2", name="b", country_code="KZ", actor_id=1,
                              ext_1c_ref=GUID_B)
    with pytest.raises(IntegrityError, match="ck_project_ext_1c_lower"), transaction.atomic():
        Project.objects.filter(pk=project.pk).update(ext_1c_ref=GUID_B.upper())
    project.refresh_from_db()
    assert project.ext_1c_ref == GUID_B


def _admin_form(project, ext_1c_ref: str):
    from django.contrib import admin
    from django.forms.models import model_to_dict
    from django.test import RequestFactory

    model_admin = admin.site._registry[Project]
    form_class = model_admin.get_form(RequestFactory().post("/"), project)
    data = {key: value for key, value in model_to_dict(project).items()
            if key in form_class.base_fields and value is not None}
    data["ext_1c_ref"] = ext_1c_ref
    return form_class(data, instance=project)


def test_admin_form_with_uppercase_ref_is_a_form_error(ctx):
    """Поле «Код в 1С» в django-admin редактируется мимо сервиса: верхний
    регистр — ошибка формы (проверка ограничений модели), а не 500 на save."""
    project = projects.create(code="П-1", name="a", country_code="KZ", actor_id=1)
    form = _admin_form(project, GUID_A.upper())
    assert not form.is_valid()
    assert "ext_1c_ref" in str(form.errors) or "регистр" in str(form.errors)
    assert _admin_form(project, GUID_A).is_valid(), _admin_form(project, GUID_A).errors


def test_linked_project_is_found_by_exact_ref(ctx):
    """Хранится только нижний регистр — связанный «Проект» находит точное
    сравнение (индекс уникальности), без ``UPPER(...)`` по столбцу."""
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    first = onec.upsert_project(_record())
    with CaptureQueriesContext(connection) as queries:
        again = onec.upsert_project(_record(guid=GUID_A.upper()))
    assert again.status == "unchanged" and again.object_id == first.object_id
    assert Project.objects.count() == 1
    assert not [q["sql"] for q in queries if re.search(r'UPPER\("\w+"\."ext_1c_ref"', q["sql"])]
