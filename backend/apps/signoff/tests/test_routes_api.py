"""HTTP-слой настройки маршрутов: ``/api/signoff/v1/routes|stages``."""

from __future__ import annotations

import pytest

from apps.signoff.models import ApprovalRoute, ApprovalRouteStage, Quorum
from apps.signoff.tests.helpers import (
    BASE,
    admin_token,
    auth,
    make_route,
    make_user,
    patch_json,
    post_json,
    token,
)
from apps.signoff.tests.testapp.models import ProbeDoc

pytestmark = pytest.mark.django_db

SUBJECT = ProbeDoc.SIGNOFF_SUBJECT_TYPE


def test_route_crud(client):
    a = make_user("a")
    admin = auth(admin_token())

    created = post_json(client, f"{BASE}/routes",
                        {"subject_type": SUBJECT, "name": "Маршрут бюджета"},
                        **admin)
    assert created.status_code == 201, created.content
    route_id = created.json()["id"]

    stage = post_json(client, f"{BASE}/routes/{route_id}/stages",
                      {"order": 1, "name": "Финансовый контроль",
                       "quorum": Quorum.ALL, "approver_ids": [a.pk]}, **admin)
    assert stage.status_code == 201, stage.content
    assert [x["user_id"] for x in stage.json()["approvers"]] == [a.pk]
    # Имя разворачивается через apps.users.interface — фронтенду нужен
    # человек, а не число.
    assert stage.json()["approvers"][0]["full_name"]

    listed = client.get(f"{BASE}/routes", **auth(token()))
    assert listed.status_code == 200
    assert len(listed.json()[0]["stages"]) == 1

    renamed = patch_json(client, f"{BASE}/routes/{route_id}",
                         {"name": "Переименованный"}, **admin)
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Переименованный"

    removed = client.delete(f"{BASE}/routes/{route_id}", **admin)
    assert removed.status_code == 204
    assert not ApprovalRoute.objects.filter(pk=route_id).exists()


def test_second_active_route_for_a_subject_is_409(client):
    admin = auth(admin_token())
    post_json(client, f"{BASE}/routes",
              {"subject_type": SUBJECT, "name": "Первый"}, **admin)

    clash = post_json(client, f"{BASE}/routes",
                      {"subject_type": SUBJECT, "name": "Второй"}, **admin)
    assert clash.status_code == 409
    assert "активный маршрут" in clash.json()["detail"]


def test_route_for_an_unregistered_subject_is_409(client):
    """Маршрут на незарегистрированный тип никогда не запустится — ловим
    на настройке, а не в момент отправки заявки."""
    clash = post_json(client, f"{BASE}/routes",
                      {"subject_type": "nosuch.model", "name": "Никуда"},
                      **auth(admin_token()))
    assert clash.status_code == 409
    assert "не зарегистрирован" in clash.json()["detail"]


def test_stage_with_an_unknown_approver_is_409(client):
    admin = auth(admin_token())
    route = make_route([(1, "Этап", Quorum.ALL, [make_user("a").pk])])

    bad = post_json(client, f"{BASE}/routes/{route.pk}/stages",
                    {"order": 2, "name": "Второй", "quorum": Quorum.ALL,
                     "approver_ids": [999_999]}, **admin)
    assert bad.status_code == 409
    assert "Не найдены пользователи" in bad.json()["detail"]


def test_stage_without_approvers_is_rejected_by_the_schema(client):
    route = make_route([(1, "Этап", Quorum.ALL, [make_user("a").pk])])
    bad = post_json(client, f"{BASE}/routes/{route.pk}/stages",
                    {"order": 2, "name": "Пустой", "quorum": Quorum.ALL,
                     "approver_ids": []}, **auth(admin_token()))
    assert bad.status_code == 422


def test_stage_approvers_are_replaced_wholesale(client):
    a, b = make_user("a"), make_user("b")
    route = make_route([(1, "Этап", Quorum.ALL, [a.pk])])
    stage = route.stages.first()

    updated = patch_json(client, f"{BASE}/stages/{stage.pk}",
                         {"approver_ids": [b.pk]}, **auth(admin_token()))
    assert updated.status_code == 200
    assert [x["user_id"] for x in updated.json()["approvers"]] == [b.pk]


def test_patch_without_approver_ids_leaves_them_alone(client):
    """``None`` — «не трогать», и это должно отличаться от «стереть»."""
    a = make_user("a")
    route = make_route([(1, "Этап", Quorum.ALL, [a.pk])])
    stage = route.stages.first()

    updated = patch_json(client, f"{BASE}/stages/{stage.pk}",
                         {"name": "Новое название"}, **auth(admin_token()))
    assert updated.status_code == 200
    assert [x["user_id"] for x in updated.json()["approvers"]] == [a.pk]


def test_emptying_the_approver_list_is_409(client):
    a = make_user("a")
    route = make_route([(1, "Этап", Quorum.ALL, [a.pk])])
    stage = route.stages.first()

    bad = patch_json(client, f"{BASE}/stages/{stage.pk}",
                     {"approver_ids": []}, **auth(admin_token()))
    assert bad.status_code == 409
    assert "хотя бы один согласующий" in bad.json()["detail"]


def test_the_last_stage_of_a_route_cannot_be_deleted(client):
    """Маршрут без этапов проходит настройку и падает только на запуске —
    то есть в руках того, кто его не настраивал."""
    a = make_user("a")
    route = make_route([(1, "Единственный", Quorum.ALL, [a.pk])])
    stage = route.stages.first()

    bad = client.delete(f"{BASE}/stages/{stage.pk}", **auth(admin_token()))
    assert bad.status_code == 409
    assert ApprovalRouteStage.objects.filter(pk=stage.pk).exists()


def test_a_non_last_stage_can_be_deleted(client):
    a, b = make_user("a"), make_user("b")
    route = make_route([
        (1, "Первый", Quorum.ALL, [a.pk]),
        (2, "Второй", Quorum.ALL, [b.pk]),
    ])
    stage = route.stages.last()

    ok = client.delete(f"{BASE}/stages/{stage.pk}", **auth(admin_token()))
    assert ok.status_code == 204


# ── Права ───────────────────────────────────────────────────────────────

def test_reading_routes_needs_only_a_token_writing_needs_admin(client):
    make_route([(1, "Этап", Quorum.ALL, [make_user("a").pk])])

    assert client.get(f"{BASE}/routes", **auth(token())).status_code == 200

    forbidden = post_json(client, f"{BASE}/routes",
                          {"subject_type": SUBJECT, "name": "Ещё один"},
                          **auth(token()))
    assert forbidden.status_code == 403


def test_anonymous_is_401(client):
    assert client.get(f"{BASE}/routes").status_code == 401


def test_subjects_lists_registered_types_and_their_route_status(client):
    listed = client.get(f"{BASE}/subjects", **auth(token()))
    assert listed.status_code == 200
    row = next(x for x in listed.json() if x["subject_type"] == SUBJECT)
    assert row["label"] == "Пробный документ"
    assert row["has_active_route"] is False

    make_route([(1, "Этап", Quorum.ALL, [make_user("a").pk])])
    again = client.get(f"{BASE}/subjects", **auth(token()))
    row = next(x for x in again.json() if x["subject_type"] == SUBJECT)
    assert row["has_active_route"] is True


def test_enums_expose_the_choice_labels(client):
    body = client.get(f"{BASE}/enums", **auth(token())).json()
    assert {x["value"] for x in body["quorum"]} == {"any", "all"}
    assert "pending" in {x["value"] for x in body["process_state"]}
