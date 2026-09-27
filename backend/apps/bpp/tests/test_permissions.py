"""Группы статей по роли (BR-010): СН — «Снабжение», ПМ — «Проектное
управление», совмещающий — обе."""

import pytest
from django.test import RequestFactory

from apps.access.models import Role, RoleAssignment, ScopeKind
from apps.access.tests.helpers import token
from apps.bpp.services.core import permissions
from htqweb.authn.jwt import decode_token


def _request(slug: str, user_id: int, *codes: str):
    for code in codes:
        RoleAssignment.objects.get_or_create(
            company_slug=slug, user_id=user_id, role=Role.objects.get(code=code),
            scope_kind=ScopeKind.COMPANY, scope_id=None)
    request = RequestFactory().get("/")
    request.token = decode_token(token(user_id=user_id, sub=str(user_id), company=slug))
    request.company = {"slug": slug}
    return request


@pytest.mark.django_db
def test_groups_follow_roles(company_context):
    slug = company_context["slug"]
    assert permissions.article_groups_for(_request(slug, 21, "bpp-sn")) == ["supply"]
    assert permissions.article_groups_for(_request(slug, 22, "bpp-pm")) == ["pm"]
    assert sorted(permissions.article_groups_for(_request(slug, 23, "bpp-sn", "bpp-pm"))) \
        == ["pm", "supply"]
    assert permissions.article_groups_for(_request(slug, 24)) == []


@pytest.mark.django_db
def test_can(company_context):
    slug = company_context["slug"]
    fd = _request(slug, 31, "bpp-fd")
    sn = _request(slug, 32, "bpp-sn")
    assert permissions.can(fd, "bpp.invoices.decision", "edit")
    assert not permissions.can(sn, "bpp.invoices.decision", "edit")
