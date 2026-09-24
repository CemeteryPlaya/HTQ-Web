"""Гейт модуля ``cms`` с НАСТОЯЩИМИ ролями (блок L, задача 8).

Не синтетические роли тестов, а ``employee-basic`` и ``services-admin`` из
миграций ``access``: правка контента (бывшие ``admin=True``) — под
``cms:write``, которого у базовой роли нет (её уровень в ``cms`` — ``read``,
инвариант L1); приглашения и конфиг конференции — под ``cms:read``, чужие
ссылки закрывает ``conference_invite_service.may_manage_invites`` (спека §7).
"""
import pytest
from django.test import Client

from apps.access.tests.helpers import post_json, token
from apps.cms.models import ConferenceInvite

COMPANY = "t-cms-gate"
BASE = "/api/cms/v1"


def _as(role_code: str, user_id: int) -> dict:
    """Заголовки вызывающего с одной настоящей ролью в компании теста."""
    from apps.access.models import Role, RoleAssignment, ScopeKind
    from apps.companies.models import Company, CompanyKind

    Company.objects.get_or_create(slug=COMPANY, defaults={
        "name": COMPANY, "kind": CompanyKind.SERVICE})
    RoleAssignment.objects.get_or_create(
        company_slug=COMPANY, user_id=user_id, role=Role.objects.get(code=role_code),
        scope_kind=ScopeKind.COMPANY, scope_id=None)
    return {"HTTP_AUTHORIZATION": f"Bearer {token(user_id=user_id, sub=str(user_id), company=COMPANY)}",
            "HTTP_X_HTQ_COMPANY": COMPANY}


@pytest.mark.django_db
def test_employee_basic_may_not_edit_news():
    resp = post_json(Client(), f"{BASE}/news/", {"title": "x"}, **_as("employee-basic", 341))
    assert resp.status_code == 403


@pytest.mark.django_db
def test_staff_without_a_role_may_not_edit_news():
    headers = _as("employee-basic", 342)
    headers["HTTP_AUTHORIZATION"] = "Bearer " + token(
        user_id=342, sub="342", company=COMPANY, is_staff=True, is_admin=True)
    assert post_json(Client(), f"{BASE}/news/", {"title": "x"}, **headers).status_code == 403


@pytest.mark.django_db
def test_services_admin_edits_news():
    resp = post_json(Client(), f"{BASE}/news/", {"title": "x"}, **_as("services-admin", 343))
    assert resp.status_code != 403


@pytest.mark.django_db
def test_employee_basic_reads_conference_config():
    assert Client().get(f"{BASE}/conference/config",
                        **_as("employee-basic", 344)).status_code != 403


def _invite(room_id="room-x", author=350) -> ConferenceInvite:
    # Прямой ``objects.create`` не проходит: ``token`` уникален, а
    # ``expires_at`` обязателен — их проставляет сервис.
    from apps.cms.services import conference_invite_service as svc

    return svc.create_invite(room_id=room_id, created_by_id=author, title="t")


@pytest.mark.django_db
def test_stranger_cannot_revoke_or_see_someone_elses_invite():
    invite = _invite()
    stranger = _as("employee-basic", 351)
    assert Client().delete(f"{BASE}/conference/invites/{invite.id}", **stranger).status_code == 404
    listed = Client().get(f"{BASE}/conference/invites?room_id=room-x", **stranger).json()
    assert listed == []


@pytest.mark.django_db
def test_author_revokes_his_invite():
    invite = _invite(author=352)
    resp = Client().delete(f"{BASE}/conference/invites/{invite.id}", **_as("employee-basic", 352))
    assert resp.status_code == 204


@pytest.mark.django_db
def test_services_admin_sees_every_invite():
    _invite()
    listed = Client().get(f"{BASE}/conference/invites?room_id=room-x",
                          **_as("services-admin", 353)).json()
    assert len(listed) == 1


@pytest.mark.django_db
def test_invite_check_survives_disabled_tasks(monkeypatch):
    from apps.cms.services import conference_invite_service as svc
    from apps.core.services import ServiceDisabled

    calls = []

    def disabled(room_id):
        calls.append(room_id)
        raise ServiceDisabled("tasks", "Модуль выключен")

    monkeypatch.setattr(svc.tasks_interface, "get_conference_event_for_room", disabled)
    invite = _invite(author=354)
    resp = Client().delete(f"{BASE}/conference/invites/{invite.id}", **_as("employee-basic", 354))
    assert resp.status_code == 204
    # Автор проходит раньше вопроса к календарю; посторонний до него доходит —
    # и получает 404, а не 500 от выключенного tasks.
    other = _invite(room_id="room-y", author=350)
    resp = Client().delete(f"{BASE}/conference/invites/{other.id}", **_as("employee-basic", 356))
    assert resp.status_code == 404
    assert calls == ["room-y"]


@pytest.mark.django_db
def test_meeting_organizer_manages_links_he_did_not_create(monkeypatch):
    """Организатор календарного события комнаты (``creator_id``) видит и
    отзывает ссылку, которую создал другой — это ссылки его встречи."""
    from apps.cms.services import conference_invite_service as svc

    def event_of(room_id):
        return ({"id": 1, "creator_id": 355, "conference_room_id": room_id}
                if room_id == "room-x" else None)

    monkeypatch.setattr(svc.tasks_interface, "get_conference_event_for_room", event_of)
    invite = _invite(author=350)
    organizer = _as("employee-basic", 355)

    listed = Client().get(f"{BASE}/conference/invites?room_id=room-x", **organizer).json()
    assert [row["id"] for row in listed] == [invite.id]
    resp = Client().delete(f"{BASE}/conference/invites/{invite.id}", **organizer)
    assert resp.status_code == 204
