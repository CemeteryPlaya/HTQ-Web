"""Договор глазами соседа: поиск для привлечения партнёра и ``visible_brief``
без запроса на строку (этап 8 A, задача 8.3, D-S8-3).

Видимость — ровно правило карточки договора ``agreements.can_view``: автор,
«все договоры», проект + группа статей, участник согласования. Внешний гейт
поиска (право на узел ``bpp.agreements`` или «все») остаётся: автор или
согласующий без роли в модуле получают пусто, как и раньше. Число запросов
не зависит от числа договоров: статьи — одним ``refdata.article_brief``,
участие — одной ``signoff.participant_subject_ids`` и только для тех, кого
не открыли автор и проект со статьёй.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from django.core.cache import cache
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.bpp.models import Agreement, AgreementStatus, Counterparty
from apps.bpp.services.agreements import agreements as service
from apps.bpp.services.agreements import neighbour
from apps.bpp.tests import stage2 as s
from apps.core.models import ServiceStatus
from apps.signoff.models import (
    ApprovalProcess,
    ApprovalProcessStage,
    ApprovalTask,
    ProcessState,
    StageState,
    TaskState,
)

pytestmark = pytest.mark.django_db

SUBJECT = "bpp.agreement"
#: Участник согласования с ролью СН, но не в проекте; автор и согласующий
#: без роли в модуле.
APPROVER_SN, AUTHOR_NO_ROLE, APPROVER_NO_ROLE = 907, 908, 909
USABLE = (AgreementStatus.ACTIVE, AgreementStatus.FULFILLED)


# ── мир ─────────────────────────────────────────────────────────────────

def _cp(reg: str) -> Counterparty:
    return Counterparty.objects.create(name=f"ТОО «{reg}»", kind="legal", country_code="KZ",
                                       reg_number=reg)


def _agreement(cp, number, *, project_id, article, author_id=1, status="active",
               **over) -> Agreement:
    return Agreement.objects.create(
        number=number, project_id=project_id, article_id=article.id, counterparty=cp,
        amount=1000, author_id=author_id, status=status, name=f"Поставка {number}",
        ext_number=number[-3:], ext_date=timezone.localdate(), **over)


def _approver(agr: Agreement, *user_ids: int) -> None:
    """Согласующий договора — строкой задачи закрытого круга (участие не
    зависит от состояния задачи и круга, ``signoff.is_participant``)."""
    process = ApprovalProcess.objects.create(subject_type=SUBJECT, subject_id=str(agr.pk),
                                             state=ProcessState.APPROVED)
    stage = ApprovalProcessStage.objects.create(process=process, order=1, name="ФД",
                                                state=StageState.APPROVED)
    for user_id in user_ids:
        ApprovalTask.objects.create(stage=stage, user_id=user_id, state=TaskState.APPROVED)


class World:
    """Проект ``proj`` с участниками СН и ПМ, статьи снабжения и ПМ."""

    def __init__(self, slug: str):
        self.slug = slug
        self.fd = s.actor(slug, s.FD, "bpp-fd")
        self.sn = s.actor(slug, s.SN, "bpp-sn")
        self.pm = s.actor(slug, s.PM, "bpp-pm")
        self.approver_sn = s.actor(slug, APPROVER_SN, "bpp-sn")
        self.author_no_role = s.actor(slug, AUTHOR_NO_ROLE)
        self.approver_no_role = s.actor(slug, APPROVER_NO_ROLE)
        self.proj = s.project(members=[s.SN, s.PM])
        self.metal, self.design = s.metal(), s.design()
        self._seq = 0

    def fill(self, cp, n: int) -> list[Agreement]:
        """``n`` годных договоров ``cp`` пяти видов по кругу (при n=3 — первые
        три: видимый по проекту, только участнику, невидимый) плюс шум, который
        поиск отсекает до прав: черновик, допсоглашение, чужой контрагент."""
        base = timezone.now()
        out = []
        for i in range(n):
            self._seq += 1
            number = f"ДГ-2026-{self._seq:06d}"
            kind = i % 5
            if kind == 0:     # проект СН и ПМ, статья снабжения — видит СН по проекту
                agr = _agreement(cp, number, project_id=self.proj.id, article=self.metal)
            elif kind == 1:   # статья не группы СН — СН видит только как согласующий
                # (у bpp-sn есть project.all, поэтому «чужой проект» СН не
                # закрывает — закрывает группа статей; ПМ не видит: проект чужой).
                agr = _agreement(cp, number, project_id=uuid.uuid4(), article=self.design)
                _approver(agr, s.SN, APPROVER_SN, APPROVER_NO_ROLE)
            elif kind == 2:   # никому из СН/ПМ не виден
                agr = _agreement(cp, number, project_id=uuid.uuid4(), article=self.design)
            elif kind == 3:   # автор — СН, проект чужой
                agr = _agreement(cp, number, project_id=uuid.uuid4(), article=self.design,
                                 author_id=s.SN)
            else:             # проект СН и ПМ, статья ПМ — видит ПМ; автор без роли
                agr = _agreement(cp, number, project_id=self.proj.id, article=self.design,
                                 author_id=AUTHOR_NO_ROLE, status="fulfilled")
                _approver(agr, s.PM)
            out.append(agr)
            # Пары с одинаковым временем — порядок внутри пары решает pk.
            Agreement.objects.filter(pk=agr.pk).update(
                created_at=base - timedelta(minutes=i // 2))
        self._seq += 1
        out.append(_agreement(cp, f"ДГ-2026-{self._seq:06d}", project_id=self.proj.id,
                              article=self.metal, status="draft"))
        self._seq += 1
        out.append(_agreement(cp, f"ДГ-2026-{self._seq:06d}", project_id=self.proj.id,
                              article=self.metal, parent_agreement=out[0]))
        return out

    def everyone(self):
        return {"ФД": self.fd, "СН": self.sn, "ПМ": self.pm,
                "участник с ролью": self.approver_sn}


def _search(actor, cp, *, limit: int = 1000) -> list[str]:
    return [row["id"] for row in neighbour.search(
        None, counterparty_id=str(cp.pk), token=actor.request.token,
        company=actor.request.company["slug"], limit=limit)]


def _expected(actor, cp) -> list[str]:
    """Эталон: годные договоры контрагента по ``-created_at, pk``, видимые по
    ``can_view``."""
    rows = Agreement.objects.filter(counterparty=cp, status__in=USABLE,
                                    parent_agreement__isnull=True).order_by("-created_at", "pk")
    return [str(a.pk) for a in rows if service.can_view(actor, a)]


def _visible_brief(actor, ids) -> set[str]:
    return set(neighbour.visible_brief(ids, token=actor.request.token,
                                       company=actor.request.company["slug"]))


# ── N+1 ─────────────────────────────────────────────────────────────────

def _count(call) -> int:
    call()                                   # прогрев кэшей процесса
    with CaptureQueriesContext(connection) as ctx:
        call()
    return len(ctx)


def test_search_query_count_does_not_grow_with_agreements(company_context):
    world = World(company_context["slug"])
    small, big = _cp("100000000001"), _cp("100000000002")
    world.fill(small, 3)
    world.fill(big, 30)
    assert not service.sees_all(world.sn)
    # В обоих наборах есть все три пути: проект, участие, невидимый.
    assert len(_search(world.sn, small)) == 2 and len(_search(world.sn, big)) > 2

    few = _count(lambda: _search(world.sn, small))
    many = _count(lambda: _search(world.sn, big))
    assert few == many, (few, many)


def test_visible_brief_query_count_does_not_grow_with_agreements(company_context):
    world = World(company_context["slug"])
    small = [str(a.pk) for a in world.fill(_cp("100000000001"), 3)]
    big = [str(a.pk) for a in world.fill(_cp("100000000002"), 30)]

    few = _count(lambda: _visible_brief(world.sn, small))
    many = _count(lambda: _visible_brief(world.sn, big))
    assert few == many, (few, many)


# ── эквивалентность с can_view ──────────────────────────────────────────

def test_participant_only_agreements_are_found_through_signoff(company_context):
    """Ветка «только как участник согласования» не вырождена: договоры вида 1
    СН и ``approver_sn`` не открыты ни автором, ни проектом со статьёй — и
    всё же в поиске есть; ПМ (не согласующий) их не видит."""
    world = World(company_context["slug"])
    cp = _cp("100000000001")
    rows = world.fill(cp, 10)
    only_approver = [rows[1], rows[6]]                     # вид 1 при i = 1, 6
    for who in (world.sn, world.approver_sn):
        found = _search(who, cp)
        for agr in only_approver:
            assert agr.author_id != who.user_id
            assert not service._sees_by_scope(who, agr)
            assert service.can_view(who, agr)
            assert str(agr.pk) in found
        assert {str(a.pk) for a in only_approver} <= set(
            _visible_brief(who, [str(a.pk) for a in rows]))
    for agr in only_approver:
        assert not service.can_view(world.pm, agr)
        assert str(agr.pk) not in _search(world.pm, cp)


def test_search_matches_can_view_for_every_role(company_context):
    world = World(company_context["slug"])
    cp = _cp("100000000001")
    world.fill(cp, 12)
    world.fill(_cp("100000000002"), 5)       # чужой контрагент — в поиск не попадает

    for who, actor in world.everyone().items():
        expected = _expected(actor, cp)
        assert expected, who
        assert _search(actor, cp) == expected, who
    # Права разные — и ответы разные: проверка не вырожденная.
    assert len({tuple(_search(a, cp)) for a in world.everyone().values()}) == 4
    assert len(_search(world.fd, cp)) == 12


def test_author_or_approver_without_a_role_gets_nothing(company_context):
    world = World(company_context["slug"])
    cp = _cp("100000000001")
    world.fill(cp, 10)
    for actor in (world.author_no_role, world.approver_no_role):
        # Карточку они бы открыли — а в поиск без права на узел не попадают.
        assert _expected(actor, cp)
        assert _search(actor, cp) == []


def test_visible_brief_matches_can_view(company_context):
    world = World(company_context["slug"])
    rows = world.fill(_cp("100000000001"), 12) + world.fill(_cp("100000000002"), 4)
    ids = [str(a.pk) for a in rows] + [str(rows[0].pk).upper(), "мусор", str(uuid.uuid4())]

    for who, actor in world.everyone().items():
        expected = {str(a.pk) for a in rows if service.can_view(actor, a)}
        assert _visible_brief(actor, ids) == expected, who
    for actor in (world.author_no_role, world.approver_no_role):
        assert _visible_brief(actor, ids) == set()


# ── лимит ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("who", ["ФД", "СН", "ПМ"])
def test_limit_returns_the_first_visible(company_context, who):
    world = World(company_context["slug"])
    cp = _cp("100000000001")
    world.fill(cp, 20)
    actor = world.everyone()[who]
    expected = _expected(actor, cp)
    assert len(expected) > 3
    for limit in (1, 2, 3):
        assert _search(actor, cp, limit=limit) == expected[:limit], (who, limit)


# ── выключенный signoff ─────────────────────────────────────────────────

def test_disabled_signoff_does_not_break_search_of_those_who_need_no_approvals(company_context):
    world = World(company_context["slug"])
    cp = _cp("100000000001")
    rows = world.fill(cp, 10)
    # У СН — контрагент, чьи договоры он видит без участия: автор и проект.
    own = _cp("100000000002")
    mine = [_agreement(own, "ДГ-2026-900001", project_id=world.proj.id, article=world.metal),
            _agreement(own, "ДГ-2026-900002", project_id=uuid.uuid4(), article=world.design,
                       author_id=s.SN)]
    expected_fd = _expected(world.fd, cp)
    expected_sn = _expected(world.sn, own)

    ServiceStatus.objects.update_or_create(app_label="signoff", defaults={"enabled": False})
    cache.clear()
    try:
        assert _search(world.fd, cp) == expected_fd
        assert len(expected_fd) == 10
        assert _visible_brief(world.fd, [str(a.pk) for a in rows]) == {str(a.pk) for a in rows}
        assert _search(world.sn, own) == expected_sn
        assert set(expected_sn) == {str(a.pk) for a in mine}
    finally:
        ServiceStatus.objects.update_or_create(app_label="signoff", defaults={"enabled": True})
        cache.clear()
