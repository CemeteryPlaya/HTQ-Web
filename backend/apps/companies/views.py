"""HTTP-слой ``/api/companies/v1/*`` — план блока A, «Контракт API».

Стиль тот же, что в ``apps.access``: ``htqweb.http.ApiView``, ``api_view``
пометодно через ``method_decorator``.

**Гейты.** Чтение и правка реестра — ``api_view(module="companies", ...)``:
функции ``companies.registry/modules/memberships`` объявлены в
``access_functions.py`` аппки. Архив, восстановление и отзыв членства —
операции платформенного уровня (архив = 404 на весь трафик компании; отзыв
членства запирает человека снаружи), поэтому ``admin=True`` плюс явная
проверка ``is_superuser``, как у каталога ролей в ``apps.access``.

**Заведения компании здесь нет** — намеренно: ``provision_company`` гонит
миграции четырёх аппок около минуты, ``gunicorn --timeout 60`` убьёт воркер
посреди DDL. Заведение — ``manage.py company_create``.
"""

from __future__ import annotations

from django.http import HttpResponse, JsonResponse
from django.utils.decorators import method_decorator

from apps.users.interface import get_user_brief
from htqweb.http import ApiView, api_view, json_error

from . import schemas
from .models import Company, CompanyMembership, CompanyStatus
from .services import lifecycle, membership_service, module_service

read = method_decorator(api_view(methods=("GET",), auth="jwt",
                                 module="companies", level="read"))


def write(method: str, body=None, status: int = 200):
    return method_decorator(api_view(methods=(method,), auth="jwt", body=body,
                                     status=status, module="companies", level="write"))


def platform(method: str, body=None, status: int = 200):
    """Платформенная операция: admin-гейт api_view + is_superuser внутри метода."""
    return method_decorator(api_view(methods=(method,), auth="jwt", body=body,
                                     status=status, admin=True))


class CompaniesView(ApiView):
    def deny_unless_platform_admin(self):
        if not self.request.token.is_superuser:
            return json_error(
                "Операция платформенного уровня: доступна только "
                "платформенному администратору", 403,
            )
        return None

    @staticmethod
    def lifecycle_error(exc: lifecycle.LifecycleError):
        return JsonResponse({"detail": exc.detail, "code": exc.code}, status=exc.status)

    @staticmethod
    def company_or_404(slug: str) -> Company:
        return lifecycle.get_company_or_raise(slug)


# ── Мои компании ─────────────────────────────────────────────────────────

class MyCompaniesView(ApiView):
    """``GET me`` — компании, где у пользователя есть членство. Без гейта модуля:
    это то, что нужно КАЖДОМУ вошедшему, чтобы переключиться."""

    @method_decorator(api_view(methods=("GET",), auth="jwt"))
    def get(self, request):
        current = request.company["slug"] if getattr(request, "company", None) else None
        rows = (
            CompanyMembership.objects
            .filter(user_id=request.token.user_id, company__status=CompanyStatus.ACTIVE)
            .select_related("company")
            .order_by("-is_default", "company__name")
        )
        return [
            schemas.MyCompany(
                slug=m.company.slug, name=m.company.name, kind=m.company.kind,
                is_default=m.is_default, is_current=(m.company.slug == current),
            )
            for m in rows
        ]


# ── Реестр ───────────────────────────────────────────────────────────────

_STATUS_FILTERS = {"all": None, "active": CompanyStatus.ACTIVE,
                   "archived": CompanyStatus.ARCHIVED}


class CompanyCollectionView(CompaniesView):
    @read
    def get(self, request):
        wanted = request.GET.get("status", "all")
        if wanted not in _STATUS_FILTERS:
            return json_error("status: ожидается all, active или archived", 422)
        qs = Company.objects.select_related("parent").order_by("name")
        if _STATUS_FILTERS[wanted] is not None:
            qs = qs.filter(status=_STATUS_FILTERS[wanted])
        return [schemas.CompanyRead.model_validate(c) for c in qs]


def _tree(companies: list[Company]) -> list[schemas.CompanyTreeNode]:
    by_parent: dict[int | None, list[Company]] = {}
    for company in companies:
        by_parent.setdefault(company.parent_id, []).append(company)

    def node(company: Company) -> schemas.CompanyTreeNode:
        return schemas.CompanyTreeNode(
            slug=company.slug, name=company.name, kind=company.kind,
            status=company.status, country=company.country,
            children=[node(c) for c in by_parent.get(company.id, [])],
        )

    # Корень — компания без родителя либо с родителем вне выборки (архивным):
    # ветка не должна пропадать из дерева из-за архива над ней.
    ids = {c.id for c in companies}
    return [node(c) for c in companies if c.parent_id is None or c.parent_id not in ids]


class CompanyTreeView(CompaniesView):
    @read
    def get(self, request):
        companies = list(Company.objects.filter(status=CompanyStatus.ACTIVE).order_by("name"))
        return _tree(companies)


class CompanyItemView(CompaniesView):
    @read
    def get(self, request, slug: str):
        try:
            company = self.company_or_404(slug)
        except lifecycle.LifecycleError as exc:
            return self.lifecycle_error(exc)
        return schemas.CompanyRead.model_validate(company)


# ── Заглушки задач 7–8 (urls.py на них ссылается уже сейчас) ───────────────

class CompanyArchiveView(CompaniesView): ...
class CompanyRestoreView(CompaniesView): ...
class CompanyModulesView(CompaniesView): ...
class CompanyModuleItemView(CompaniesView): ...
class CompanyMembershipsView(CompaniesView): ...
class CompanyMembershipItemView(CompaniesView): ...
