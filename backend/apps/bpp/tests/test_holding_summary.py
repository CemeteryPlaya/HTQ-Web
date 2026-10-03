"""«Сводка группы по БЗО» — ``GET /api/bpp/v1/holding/summary`` (A8.1, D-S7-8).

Две настоящие схемы: холдинг и дочерняя. Главные проверки: суммы сводки равны
реестрам компаний (``invoices.read.visible`` по своим вкладкам), ручка открыта
только на поддомене холдинга и только с узлом ``bpp.holding``, читатели вне
``use_holding()`` не читают, а без представлений — 503.
"""

from __future__ import annotations

import itertools
import uuid
from decimal import Decimal

import pytest
from django.core.cache import cache
from django.db import connection
from django.db.models import Sum
from django.test import Client

from apps.access.models import Role, RoleAssignment, RolePermission, ScopeKind
from apps.access.tests.helpers import token as make_token
from apps.bpp.holding_models import HoldingContextRequired, HoldingInvoice
from apps.bpp.models import (
    Agreement,
    AgreementStatus,
    Budget,
    BudgetLine,
    BudgetStatus,
    BudgetVersion,
    Counterparty,
    Invoice,
    InvoiceStatus,
    VersionState,
)
from apps.bpp.services.invoices import read as registry
from apps.bpp.tests import stage2 as s
from apps.companies.models import Company, CompanyKind
from apps.companies.services import holding_views
from apps.users.models import User, UserStatus
from htqweb.tenancy.db import use_company

D = Decimal
URL = "/api/bpp/v1/holding/summary"
VIEWER, PLAIN = 7201, 7202
_n = itertools.count(1)

pytestmark = pytest.mark.django_db(transaction=True)


def _drop_holding() -> None:
    with connection.cursor() as cur:
        cur.execute("DROP SCHEMA IF EXISTS holding CASCADE")


@pytest.fixture
def group(two_company_schemas):
    holding, child = two_company_schemas
    Company.objects.filter(slug=holding).update(kind=CompanyKind.HOLDING)
    Company.objects.filter(slug=child).update(parent=Company.objects.get(slug=holding))
    cache.clear()
    yield holding, child
    _drop_holding()
    cache.clear()


def _invoice(status: str, amount, cp) -> Invoice:
    k = next(_n)
    return Invoice.objects.create(
        number=f"СЧ-2026-8{k:05d}", project_id=uuid.uuid4(), article_id=uuid.uuid4(),
        counterparty=cp, ext_number=str(k), ext_date="2026-10-01", amount=D(str(amount)),
        amount_kzt=D(str(amount)), status=status, author_id=VIEWER)


def _budget(limit, *, currency="KZT", status=BudgetStatus.APPROVED, version=VersionState.ACTIVE):
    k = next(_n)
    budget = Budget.objects.create(project_id=uuid.uuid4(), number=f"Б-{k}",
                                   currency_code=currency, status=status)
    ver = BudgetVersion.objects.create(budget=budget, version_no=1, state=version)
    BudgetLine.objects.create(version=ver, article_id=uuid.uuid4(), limit_amount=D(str(limit)))
    return budget


def _fill(slug: str, scale: int) -> None:
    with use_company(slug):
        cp = Counterparty.objects.create(name="ТОО", kind="legal", country_code="KZ",
                                         reg_number=f"9{scale:011d}", verified_override=True)
        _budget(1000 * scale)
        _budget(500 * scale)
        _budget(9999, status=BudgetStatus.DRAFT, version=VersionState.DRAFT)  # не входит
        _budget(7777, currency="USD")  # не KZT: в сумму не входит
        _invoice(InvoiceStatus.TO_PAY, 100 * scale, cp)
        _invoice(InvoiceStatus.PARTIALLY_PAID, 50 * scale, cp)
        _invoice(InvoiceStatus.PAID, 30 * scale, cp)
        _invoice(InvoiceStatus.AWAITING_DOCS, 7 * scale, cp)
        _invoice(InvoiceStatus.DOCS_PROVIDED, 3 * scale, cp)
        _invoice(InvoiceStatus.CLOSED, 20 * scale, cp)
        _invoice(InvoiceStatus.DRAFT, 5555, cp)  # ни к оплате, ни оплачен
        for status in (AgreementStatus.ACTIVE, AgreementStatus.ACTIVE, AgreementStatus.DRAFT):
            Agreement.objects.create(
                number=f"ДГ-2026-9{next(_n):05d}", project_id=uuid.uuid4(),
                article_id=uuid.uuid4(), counterparty=cp, ext_number="1",
                amount=D("10"), status=status, author_id=VIEWER)


def _user(user_id: int) -> None:
    if not User.objects.filter(pk=user_id).exists():
        User.objects.create(id=user_id, username=f"h{user_id}", email=f"h{user_id}@htq.test",
                            password="x", status=UserStatus.ACTIVE)


def _role_with(company: str, user_id: int, code: str, *nodes: str) -> None:
    _user(user_id)
    role, _ = Role.objects.get_or_create(code=code, defaults={"title": code})
    for node in nodes:
        RolePermission.objects.update_or_create(
            role=role, node=node,
            defaults={"can_view": True, "can_create": False, "can_edit": False,
                      "can_delete": False})
    RoleAssignment.objects.get_or_create(
        company_slug=company, user_id=user_id, role=role,
        scope_kind=ScopeKind.COMPANY, scope_id=None)


def _get(slug: str, user_id: int, **claims):
    tok = make_token(user_id=user_id, sub=str(user_id), company=slug, **claims)
    return Client().get(URL, HTTP_AUTHORIZATION=f"Bearer {tok}", HTTP_X_HTQ_COMPANY=slug)


def _registry_totals(slug: str, tab: str | None = None, statuses=None):
    actor = s.actor(slug, 7290, superuser=True)
    filters = {"tab": tab} if tab else {"statuses": statuses}
    with use_company(slug):
        rows = registry.visible(actor, filters)
        return rows.count(), rows.aggregate(t=Sum("amount_kzt"))["t"] or D("0.00")


def test_summary_equals_company_registries(group):
    holding, child = group
    _fill(holding, 1)
    _fill(child, 3)
    holding_views.rebuild_holding_views()
    _role_with(holding, VIEWER, "t-holding-viewer", "bpp.holding")

    resp = _get(holding, VIEWER)

    assert resp.status_code == 200, resp.content
    rows = {r["company_slug"]: r for r in resp.json()["companies"]}
    assert set(rows) >= {holding, child}
    for slug, scale in ((holding, 1), (child, 3)):
        row = rows[slug]
        count, amount = _registry_totals(slug, "to_pay")
        assert (row["invoices_to_pay"]["count"], D(str(row["invoices_to_pay"]["amount_kzt"]))) \
            == (count, amount) == (2, D(150 * scale))
        count, amount = _registry_totals(
            slug, statuses=[InvoiceStatus.PAID, InvoiceStatus.AWAITING_DOCS,
                            InvoiceStatus.DOCS_PROVIDED, InvoiceStatus.CLOSED])
        assert (row["invoices_paid"]["count"], D(str(row["invoices_paid"]["amount_kzt"]))) \
            == (count, amount) == (4, D(60 * scale))
        assert row["budgets"] == 3  # два KZT и один USD, черновик не считается
        assert row["budgets_other_currency"] == 1
        assert D(str(row["limit_kzt"])) == D(1500 * scale)
        assert row["agreements_active"] == 2
    totals = resp.json()["totals"]
    assert D(str(totals["limit_kzt"])) == D(6000)
    assert totals["agreements_active"] == 4


def test_child_subdomain_is_refused_even_for_an_inheriting_director(group):
    holding, child = group
    _fill(child, 1)
    holding_views.rebuild_holding_views()
    _role_with(child, VIEWER, "t-holding-viewer", "bpp.holding")

    resp = _get(child, VIEWER)

    assert resp.status_code == 403


def test_without_the_node_is_forbidden(group):
    holding, _ = group
    holding_views.rebuild_holding_views()
    # модульная роль с правами на весь модуль, но без строки узла: EXPLICIT_ONLY
    _role_with(holding, PLAIN, "t-bpp-wide", "bpp", "bpp.invoices")

    resp = _get(holding, PLAIN)

    assert resp.status_code == 403
    assert resp.json()["code"] == "E-ACC-01"


def test_superuser_passes_on_the_holding(group):
    holding, _ = group
    holding_views.rebuild_holding_views()
    _user(9301)

    assert _get(holding, 9301, is_superuser=True, is_staff=True).status_code == 200


def test_views_missing_is_503_not_zeros(group):
    holding, _ = group
    _drop_holding()
    _role_with(holding, VIEWER, "t-holding-viewer", "bpp.holding")

    resp = _get(holding, VIEWER)

    assert resp.status_code == 503


def test_reader_outside_use_holding_is_refused(group):
    with pytest.raises(HoldingContextRequired):
        HoldingInvoice.objects.count()
