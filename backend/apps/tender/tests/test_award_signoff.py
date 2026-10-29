"""Утверждение выбора «Проверка качества → ФД» (T5.2; спека этапа 5, §3 T5.2;
T-11, T-13, S5-08, S5-09).

Маршрут в тестах — поимённо (ФД — пользователь), этап проверки качества —
``approver_kind="subject"``: исполнителя называет сам тендер (назначенный
проверяющий, иначе держатели должности «Технический директор»)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from apps.bpp import interface as bpp_interface
from apps.signoff import interface as signoff
from apps.tender.models import Invitation, Tender
from apps.tender.tests import helpers as h
from apps.tender.tests.test_award import cheapest, line, put
from apps.tender.tests.test_comparison import _opened
from htqweb.tenancy.db import use_company

pytestmark = pytest.mark.django_db
SUBJECT = "tender.award"


def route():
    return signoff.configure_route(
        subject_type=SUBJECT, name="Выбор поставщиков",
        stages=[{"order": 1, "name": "Проверка качества", "quorum": "any",
                 "approver_kind": "subject", "approver_key": "quality_reviewer"},
                {"order": 2, "name": "ФД", "quorum": "any", "approver_kind": "users",
                 "user_ids": [h.FD]}],
        flags={"forbid_self_approval": True, "reject_comment_min": 10})


def td_position(user_id: int = h.TD) -> None:
    from apps.hr.models import Department, Employee, Position

    dept, _ = Department.objects.get_or_create(path="tender-dir", defaults={"name": "Дирекция"})
    position = Position.objects.create(title="Технический директор", department=dept,
                                       weight=700)
    Employee.objects.create(user_id=user_id, first_name="Техдир", last_name="Тестов",
                            email=f"td{user_id}@htq.test", department=dept, position=position,
                            hire_date="2024-01-01")


@pytest.fixture
def world(company_context):
    slug = company_context["slug"]
    h.staff(slug)
    world = _opened(slug)
    with use_company(slug):
        route()
    return world


def _version(world) -> int:
    with use_company(world.slug):
        return Tender.objects.get(pk=world.tender.pk).version


def submit(world, user_id=h.SN):
    return h.call("post", f"tenders/{world.tender.id}/award/submit", world.slug, user_id,
                  {"version": _version(world)})


def pending(world) -> list[dict]:
    with use_company(world.slug):
        process = signoff.get_process_for(SUBJECT, str(world.tender.pk))
    if not process or process.get("state") != "pending":
        return []
    # Задачи заводятся на все этапы сразу — ждёт решения только активный этап.
    return [t for st in process["stages"] if st["state"] == "active"
            for t in st["tasks"] if t["state"] == "pending"]


def decide(world, user_id: int, decision: str, comment: str = "") -> None:
    task = next(t for t in pending(world) if t["user_id"] == user_id)
    with use_company(world.slug):
        result = signoff.decide_many(actor_id=user_id, items=[
            {"task_id": task["id"], "decision": decision, "comment": comment}])[0]
    assert result.get("ok"), result


def status(world) -> str:
    with use_company(world.slug):
        return Tender.objects.get(pk=world.tender.pk).status


def test_td_by_position_gets_the_task(world):
    with use_company(world.slug):
        td_position()
    lines, extras = cheapest(world)
    assert put(world, lines, extras).status_code == 200
    resp = submit(world)
    assert resp.status_code == 200, resp.content
    assert status(world) == "on_approval"
    assert [t["user_id"] for t in pending(world)] == [h.TD]


def test_assigned_reviewer_gets_the_task(world):
    h.user(h.SN2)
    h.grant(world.slug, h.SN2, "tender-quality")
    resp = h.call("patch", f"tenders/{world.tender.id}", world.slug, h.SN,
                  {"version": _version(world), "quality_reviewer_user_id": h.SN2})
    assert resp.status_code == 200, resp.content
    lines, extras = cheapest(world)
    assert put(world, lines, extras).status_code == 200
    assert submit(world).status_code == 200
    assert [t["user_id"] for t in pending(world)] == [h.SN2]
    late = h.call("patch", f"tenders/{world.tender.id}", world.slug, h.SN,
                  {"version": _version(world), "quality_reviewer_user_id": h.TD})
    assert late.status_code == 409                     # на идущем процессе — нельзя (S5-08)


def test_fd_approval_awards(world):
    with use_company(world.slug):
        td_position()
    lines, extras = cheapest(world)
    put(world, lines, extras)
    submit(world)
    decide(world, h.TD, "approve")
    assert status(world) == "on_approval"
    decide(world, h.FD, "approve")
    assert status(world) == "awarded"
    with use_company(world.slug):
        got = {k: Invitation.objects.get(pk=v.pk).status for k, v in world.inv.items()}
    assert got == {"A": "awarded", "B": "awarded", "C": "not_awarded", "D": "declined",
                   "E": "expired"}
    card = h.call("get", f"tenders/{world.tender.id}", world.slug, h.SN).json()
    assert "award" not in card["allowed_actions"]


def test_return_goes_to_rework_and_resubmit_starts_new_round(world):
    with use_company(world.slug):
        td_position()
    lines, extras = cheapest(world)
    put(world, lines, extras)
    submit(world)
    decide(world, h.TD, "approve")
    decide(world, h.FD, "rework", "Уточните сроки поставки у B")
    assert status(world) == "rework"
    with use_company(world.slug):
        assert Tender.objects.get(pk=world.tender.pk).status_comment == "Уточните сроки поставки у B"
    again = put(world, lines[:2], extras)
    assert again.status_code == 200, again.content
    resubmitted = submit(world)
    assert resubmitted.status_code == 200, resubmitted.content
    assert status(world) == "on_approval"
    assert [t["user_id"] for t in pending(world)] == [h.TD]      # новый раунд с начала


def test_reject_is_rework_too(world):
    with use_company(world.slug):
        td_position()
    lines, extras = cheapest(world)
    put(world, lines, extras)
    submit(world)
    decide(world, h.TD, "reject", "Аналог B не подходит по марке стали")
    assert status(world) == "rework"


def test_deficit_blocks_submit(world, monkeypatch):
    with use_company(world.slug):
        td_position()
    # Всё у C — товар дороже плана на 258 000, свободно по статье лишь 100 000.
    lines = [{"line_id": line(world, "C", n), "comment": "Берём у одного поставщика"}
             for n in (1, 2, 3)]
    assert put(world, lines, comment="Один поставщик на всё — проще приёмка").status_code == 200
    monkeypatch.setattr(bpp_interface, "budget_available", lambda *a, **kw: bpp_interface.BudgetFigures(
        limit=Decimal("10000000"), committed=Decimal("9900000"), available=Decimal("100000"),
        currency_code="KZT"))
    resp = submit(world)
    assert (resp.status_code, resp.json()["code"]) == (422, "E-TND-11")
    deficit = resp.json()["details"]["deficits"][0]
    assert (Decimal(deficit["over"]), Decimal(deficit["available"])) == (
        Decimal("258000.00"), Decimal("100000"))
    assert status(world) == "opened"


def test_missing_rate_blocks_submit(world):
    from apps.refdata.models import ExchangeRate

    with use_company(world.slug):
        td_position()
    lines, extras = cheapest(world)              # B — в USD
    put(world, lines, extras)
    with use_company(world.slug):
        from apps.tender.models import Award
        Award.objects.filter(offer__invitation=world.inv["B"]).update(amount_kzt=None)
        ExchangeRate.objects.filter(currency_code="USD").delete()
    resp = submit(world)
    assert (resp.status_code, resp.json()["code"]) == (422, "E-TND-10")


def test_empty_award_cannot_be_submitted(world):
    resp = submit(world)
    assert resp.status_code == 422


def test_no_route_is_409(company_context):
    slug = company_context["slug"]
    h.staff(slug)
    world = _opened(slug)
    lines, extras = cheapest(world)
    put(world, lines, extras)
    resp = submit(world)
    assert (resp.status_code, resp.json()["code"]) == (409, "E-SGN-01")
    assert status(world) == "opened"


def test_summary_and_describe_for_the_inbox(world):
    with use_company(world.slug):
        td_position()
    lines, extras = cheapest(world)
    put(world, lines, extras)
    submit(world)
    from apps.signoff.services import registry

    with use_company(world.slug):
        described = registry.get_subject(SUBJECT).describe(world.tender.pk)
        summary = registry.summary_for(SUBJECT, world.tender.pk)
    assert world.tender.number in described["title"]
    assert described["url"] == f"/tender/tenders/{world.tender.pk}"
    rows = {row["supplier"] for row in summary["lines"]["rows"]}
    assert rows == {world.inv["A"].name, world.inv["B"].name}


def test_author_cannot_approve_own_award(world):
    """Автор выбора — сам держатель должности ТД (forbid_self_approval): его
    группа пропускается, решать за себя он не может."""
    with use_company(world.slug):
        td_position(user_id=h.SN)
    lines, extras = cheapest(world)
    put(world, lines, extras)
    resp = submit(world)
    assert resp.status_code == 200, resp.content
    assert h.SN not in [t["user_id"] for t in pending(world)]
