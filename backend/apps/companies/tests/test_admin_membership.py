"""Членство, заведённое через django-admin, обязано получить базовую роль.

Находка n1 финального ревью блока I.2 (задача 9): ``CompanyMembershipAdmin``
сохранял строку напрямую (``ModelAdmin.save_model`` по умолчанию — простой
``obj.save()``), в обход ``membership_service.grant_membership`` — а именно
``grant_membership`` выдаёт участнику базовую роль ``employee-basic``
(``apps.access.interface.ensure_basic_role``). Без роли человек состоит в
компании, но получает 403 на ``users/options`` и на весь ``tasks``. Админка —
такой же вход в платформу, как API (``POST companies/<slug>/memberships``,
``apps/companies/views.py``), и обязана давать тот же результат.
"""

from __future__ import annotations

import pytest
from django.contrib.admin.sites import AdminSite
from django.test import Client

from apps.access.models import RoleAssignment
from apps.companies.admin import CompanyMembershipAdmin
from apps.companies.models import Company, CompanyMembership
from apps.users.models import User, UserStatus


@pytest.mark.django_db
def test_membership_created_in_django_admin_grants_the_basic_role(company_row):
    """Админка — такой же вход, как API: без базовой роли человек получит 403.

    Находка n1 финального ревью блока I: ModelAdmin сохранял строку напрямую.
    """
    company = Company.objects.get(slug=company_row)
    admin = CompanyMembershipAdmin(CompanyMembership, AdminSite())
    obj = CompanyMembership(company=company, user_id=42)

    admin.save_model(request=None, obj=obj, form=None, change=False)

    assert RoleAssignment.objects.filter(
        company_slug=company_row, user_id=42, role__code="employee-basic",
    ).exists()


@pytest.mark.django_db
def test_membership_created_in_django_admin_sets_obj_pk(company_row):
    """После ``save_model`` объект обязан нести pk уже существующей строки.

    Django использует ``obj.pk`` сразу после ``save_model`` для сообщения
    "добавлено успешно" и редиректа (``ModelAdmin.response_add``). Сервис
    создаёт строку САМ (``get_or_create`` внутри ``grant_membership``) — если
    ``save_model`` не перенесёт её pk обратно в переданный ``obj``, у него
    останется ``pk=None``, и построение ссылки на объект в админке упадёт.
    """
    company = Company.objects.get(slug=company_row)
    admin = CompanyMembershipAdmin(CompanyMembership, AdminSite())
    obj = CompanyMembership(company=company, user_id=43)

    admin.save_model(request=None, obj=obj, form=None, change=False)

    assert obj.pk is not None
    row = CompanyMembership.objects.get(company=company, user_id=43)
    assert obj.pk == row.pk


@pytest.mark.django_db
def test_membership_add_form_through_django_admin_client_grants_the_basic_role(company_row):
    """Сквозной путь: POST на форму добавления в /django-admin/, а не прямой
    вызов ``save_model`` — редирект (302) и реально применённая роль."""
    company = Company.objects.get(slug=company_row)
    superuser = User.objects.create(
        username="root-admin-membership", email="root-admin-membership@htq.test",
        password="x", status=UserStatus.ACTIVE, is_staff=True, is_superuser=True,
    )
    superuser.set_password("Adm1n!Pass")
    superuser.save()

    client = Client()
    client.force_login(superuser)

    resp = client.post(
        "/django-admin/companies/companymembership/add/",
        data={"user_id": "44", "company": str(company.id), "is_default": ""},
    )

    assert resp.status_code == 302
    assert CompanyMembership.objects.filter(company=company, user_id=44).exists()
    assert RoleAssignment.objects.filter(
        company_slug=company_row, user_id=44, role__code="employee-basic",
    ).exists()
