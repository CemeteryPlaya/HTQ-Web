"""Согласование между компаниями в модуле (мастер-план БЗО, B8.1).

Две настоящие схемы: ``alpha`` — холдинг, ``beta`` — дочерняя. Директора —
в штате холдинга, у дочерней их нет (Q-B15, Q-E02):

* счёт дочерней уходит ФД холдинга, и тот решает его прямо из очереди
  холдинга — статус счёта, уведомление автору и журнал пишутся в дочернюю;
* карточка процесса в холдинге несёт сводку счёта с позициями;
* ``bpp_configure_routes`` на дочерней находит директоров в холдинге и
  говорит, откуда взята каждая должность.
"""

from __future__ import annotations

import json
from decimal import Decimal
from io import StringIO
from types import SimpleNamespace

import pytest
from django.core.cache import cache
from django.core.management import CommandError, call_command
from django.test import Client
from django.utils import timezone

from apps.access.tests.helpers import token
from apps.bpp.models import InvoiceStatus
from apps.bpp.services.invoices import invoices as service
from apps.bpp.tests import stage2 as s
from apps.bpp.tests.test_files import memory_storage  # noqa: F401  (фикстура)
from apps.bpp.tests.test_invoices import _approved_request, _attach, _counterparty
from apps.companies.models import Company, CompanyKind
from apps.hr.models import Department, Employee, EmployeeStatus, Position
from apps.notifications.models import Notification
from apps.signoff import interface as signoff
from apps.signoff.models import ApprovalEvent, ApprovalRoute, ApprovalTask
from apps.users.models import User, UserStatus
from htqweb.tenancy.db import use_company

pytestmark = pytest.mark.django_db
SIGNOFF = "/api/signoff/v1"
DIRECTORS = ("Генеральный директор", "Финансовый директор", "Технический директор",
             "Операционный директор")


@pytest.fixture
def group(two_company_schemas):
    holding, child = two_company_schemas
    Company.objects.filter(slug=holding).update(kind=CompanyKind.HOLDING)
    row = Company.objects.get(slug=child)
    row.parent = Company.objects.get(slug=holding)
    row.save(update_fields=["parent"])
    cache.clear()
    return SimpleNamespace(holding=holding, child=child)


def _staff(company: str, titles, *, holders: dict | None = None, path: str = "b81-dir") -> dict:
    """Должности ``titles`` в штате ``company``; ``holders`` — ``{title: user_id}``."""
    holders = holders or {}
    with use_company(company):
        dept, _ = Department.objects.get_or_create(path=path, defaults={"name": f"Дирекция {path}"})
        ids = {}
        for weight, title in enumerate(titles, start=700):
            pos = Position.objects.create(title=title, department=dept, weight=weight)
            ids[title] = pos.pk
            if title in holders:
                s.user(holders[title])
                Employee.objects.create(
                    user_id=holders[title], first_name="Тест", last_name=title,
                    email=f"{company}-{holders[title]}@htq.test", department=dept, position=pos,
                    hire_date="2024-01-01", status=EmployeeStatus.ACTIVE)
    return ids


def _holding_headers(group, user_id: int) -> dict:
    return {"HTTP_X_HTQ_COMPANY": group.holding,
            "HTTP_AUTHORIZATION": "Bearer " + token(user_id=user_id, sub=str(user_id),
                                                    company=group.holding)}


def _child_invoice(group, fd_position: int):
    """Счёт дочерней «На рассмотрении ФД»; этап ФД — должность холдинга."""
    with use_company(group.child):
        s.user(s.SN)
        proj = s.project(members=[s.SN])
        s.approved_budget(group.child, proj, {s.metal(): 20_000_000})
        s.request_route()
        signoff.configure_route(
            subject_type="bpp.invoice", name="Счёт: ФД холдинга",
            stages=[{"order": 1, "name": "ФД", "quorum": "any",
                     "positions": [{"company": group.holding, "position_id": fd_position}],
                     "requirement_key": "bpp:budget"}],
            flags={"reject_comment_min": 10, "lazy_resolution": True,
                   "allow_direct_decisions": True})
        sn = s.actor(group.child, s.SN, "bpp-sn")
        req = _approved_request(sn, proj, Decimal("150000"))
        inv = service.create_from_plan(sn, [str(item.id) for item in req.items.all()])
        inv, _ = service.update_draft(sn, inv.id, expected_version=None, data={
            "counterparty_id": str(_counterparty().pk), "ext_number": "145",
            "ext_date": timezone.localdate()})
        _attach(inv)
        inv = service.submit(sn, inv.id, expected_version=None)
        task = ApprovalTask.objects.select_related("stage").get(
            stage__process__subject_id=str(inv.pk), user_id=s.FD)
    return inv, task


def test_holding_fd_pays_child_invoice_from_holding(group, memory_storage):
    fd_position = _staff(group.holding, ["Финансовый директор"],
                         holders={"Финансовый директор": s.FD})["Финансовый директор"]
    inv, task = _child_invoice(group, fd_position)
    assert inv.status == InvoiceStatus.UNDER_REVIEW
    client = Client()

    queue = client.get(f"{SIGNOFF}/tasks/mine/all", **_holding_headers(group, s.FD)).json()
    resp = client.post(f"{SIGNOFF}/companies/{group.child}/tasks/{task.pk}/decision",
                       data=json.dumps({"decision": "approve"}),
                       content_type="application/json", **_holding_headers(group, s.FD))

    assert [(row["company"]["slug"], row["direct_allowed"]) for row in queue] == \
        [(group.child, True)]
    assert resp.status_code == 200, resp.content
    with use_company(group.child):
        inv.refresh_from_db()
        event = ApprovalEvent.objects.get(process_id=task.stage.process_id, kind="task_approved")
    assert inv.status == InvoiceStatus.TO_PAY
    assert inv.planned_pay_date == inv.due_date
    assert event.payload["decided_from"] == group.holding
    # Автор — в дочерней, и уведомление несёт её метку, а не холдинга.
    assert Notification.objects.filter(recipient_id=s.SN, company_slug=group.child,
                                       event="signoff.approved").exists()


def test_holding_card_shows_invoice_summary(group, memory_storage):
    fd_position = _staff(group.holding, ["Финансовый директор"],
                         holders={"Финансовый директор": s.FD})["Финансовый директор"]
    inv, task = _child_invoice(group, fd_position)

    card = Client().get(f"{SIGNOFF}/companies/{group.child}/processes/{task.stage.process_id}",
                        **_holding_headers(group, s.FD)).json()

    fields = {row["label"]: row["value"] for row in card["summary"]["fields"]}
    assert fields["Контрагент"].startswith("ТОО «Альфа»")
    assert fields["Сумма"] == "150 000,00 KZT"
    assert fields["Аванс"] == "Нет"
    lines = card["summary"]["lines"]
    assert [column["key"] for column in lines["columns"]] == \
        ["request", "name", "qty", "uom", "amount"]
    assert lines["rows"][0]["amount"] == "150 000,00 KZT"
    assert card["direct_allowed"] is True
    assert card["subject_url"] == f"/bpp/invoices/{inv.pk}"
    assert card["company"]["slug"] == group.child


# ── команда маршрутов ───────────────────────────────────────────────────

def _run(slug, *args) -> str:
    out = StringIO()
    call_command("bpp_configure_routes", "--company", slug, *args, stdout=out)
    return out.getvalue()


def test_child_routes_take_directors_from_holding(group):
    outsider = User.objects.create(username="gd-holding", email="gd-holding@htq.test",
                                   password="x", status=UserStatus.ACTIVE)
    holding = _staff(group.holding, DIRECTORS,
                     holders={"Генеральный директор": outsider.pk})
    own = _staff(group.child, ["Технический директор"], path="b81-child")

    out = _run(group.child)

    fd, gd = holding["Финансовый директор"], holding["Генеральный директор"]
    assert f"Финансовый директор: должность #{fd} (компания {group.holding})" in out
    assert f"Технический директор: должность #{own['Технический директор']} (своя компания)" in out
    # Держатель ГД холдинга без членства в дочерней — предупреждение (A8.1).
    assert f"нет членства в {group.child}" in out and str(outsider.pk) in out
    with use_company(group.child):
        invoice = ApprovalRoute.objects.get(subject_type="bpp.invoice", is_active=True)
        role = invoice.stages.get().roles.get()
        request = ApprovalRoute.objects.get(subject_type="bpp.purchase_request", is_active=True)
        td_role = request.stages.get(order=1).roles.get()
    assert (role.position_company, role.position_id) == (group.holding, fd)
    assert (td_role.position_company, td_role.position_id) == ("", own["Технический директор"])
    assert (invoice.escalation_position_company, invoice.escalation_position_id) == \
        (group.holding, gd)
    assert invoice.no_executor_notify_foreign == [{"company": group.holding, "position_id": gd}]
    assert invoice.self_skip_notify_foreign == [{"company": group.holding, "position_id": fd}]


def test_explicit_holding_position_override(group):
    holding = _staff(group.holding, DIRECTORS)
    _run(group.child, "--fd", f"{group.holding}:{holding['Финансовый директор']}")
    with use_company(group.child):
        role = ApprovalRoute.objects.get(subject_type="bpp.invoice").stages.get().roles.get()
    assert (role.position_company, role.position_id) == \
        (group.holding, holding["Финансовый директор"])


def test_command_refuses_company_without_schema(group):
    with pytest.raises(CommandError, match="нет схемы"):
        _run("no-such-company")
