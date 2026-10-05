"""Уведомление «бюджет утверждён» (ТЗ §16.2 п.1, остаток B этапа 2, B-5):
снабженцам компании и ПМ проекта; директорам, чужим ПМ и самому ФД — нет."""

from __future__ import annotations

import pytest
from django.core.cache import cache

from apps.bpp.services.budget import budgets
from apps.bpp.tests import stage2 as s
from apps.companies.models import Company, CompanyMembership
from apps.core.models import ServiceStatus
from apps.notifications import interface as notifications

pytestmark = pytest.mark.django_db
PM_OTHER = 908
SN_LEFT = 911  # роль осталась, членство в компании отозвано


def _titles(slug: str, user_id: int) -> list[str]:
    return [row["title"] for row in notifications.latest(user_id, company_slug=slug)
            if row.get("target_type") == "bpp.budget"]


def _people(slug: str):
    """Роли и членство в компании: ``holders_of`` уведомляет только тех, кто
    может войти в компанию, — назначения ролей переживают отзыв членства."""
    company = Company.objects.get(slug=slug)
    for user_id, role in ((s.SN, "bpp-sn"), (s.SN2, "bpp-sn"), (s.PM, "bpp-pm"),
                          (PM_OTHER, "bpp-pm"), (s.TD, "bpp-td"), (SN_LEFT, "bpp-sn")):
        s.grant(slug, user_id, role)
        if user_id != SN_LEFT:
            CompanyMembership.objects.get_or_create(company=company, user_id=user_id)


def test_budget_approval_notifies_supply_and_project_pms_only(company_context):
    slug = company_context["slug"]
    _people(slug)
    proj = s.project(manager=s.PM)

    budget = s.approved_budget(slug, proj, {s.metal(): 1000})

    expected = "Бюджет проекта П-015 утверждён. Статьи открыты для заявок"
    assert _titles(slug, s.SN) == [expected]
    assert _titles(slug, s.SN2) == [expected]
    assert _titles(slug, s.PM) == [expected]
    assert _titles(slug, PM_OTHER) == []   # ПМ не из проекта (BR-014)
    assert _titles(slug, s.TD) == []       # директор заявок не создаёт
    assert _titles(slug, s.FD) == []       # сам утвердивший
    assert _titles(slug, SN_LEFT) == []    # не участник компании
    row = notifications.latest(s.SN, company_slug=slug)[0]
    assert row["url"] == f"/bpp/budgets/{budget.pk}"


def test_correction_approval_says_limits_changed(company_context):
    slug = company_context["slug"]
    _people(slug)
    proj = s.project(manager=s.PM)
    budget = s.approved_budget(slug, proj, {s.metal(): 1000})
    fd = s.actor(slug, s.FD, "bpp-fd")
    budgets.start_correction(fd, budget.id, expected_version=None)
    budgets.save_correction(fd, budget.id, expected_version=None,
                            lines=[{"article_id": str(s.metal().id), "limit_amount": 2000}])

    budgets.approve_correction(fd, budget.id, expected_version=None,
                               comment="Рост цен на металл у поставщиков")

    assert _titles(slug, s.SN)[0] == ("Корректировка бюджета проекта П-015 утверждена. "
                                      "Лимиты статей обновлены")


def test_disabled_notification_center_does_not_block_approval(company_context):
    slug = company_context["slug"]
    _people(slug)
    ServiceStatus.objects.update_or_create(app_label="notifications",
                                           defaults={"enabled": False})
    cache.clear()

    budget = s.approved_budget(slug, s.project(manager=s.PM), {s.metal(): 1000})

    assert budget.status == "approved"
    ServiceStatus.objects.update_or_create(app_label="notifications",
                                           defaults={"enabled": True})
    cache.clear()
    assert _titles(slug, s.SN) == []
