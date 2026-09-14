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

    @write("PATCH", body=schemas.CompanyPatch)
    def patch(self, request, slug: str, data: schemas.CompanyPatch):
        kwargs = {"name": data.name, "kind": data.kind, "country": data.country}
        if "parent_slug" in data.model_fields_set:
            kwargs["parent_slug"] = data.parent_slug
        try:
            company = lifecycle.update_company(slug, **kwargs)
        except lifecycle.LifecycleError as exc:
            return self.lifecycle_error(exc)
        return schemas.CompanyRead.model_validate(company)


# ── Архив и восстановление — платформенные операции ─────────────────────────

class CompanyArchiveView(CompaniesView):
    @platform("POST")
    def post(self, request, slug: str):
        denied = self.deny_unless_platform_admin()
        if denied is not None:
            return denied
        try:
            company, _changed = lifecycle.archive_company(slug)
        except lifecycle.LifecycleError as exc:
            return self.lifecycle_error(exc)
        return schemas.CompanyRead.model_validate(company)


class CompanyRestoreView(CompaniesView):
    @platform("POST")
    def post(self, request, slug: str):
        denied = self.deny_unless_platform_admin()
        if denied is not None:
            return denied
        try:
            company, _changed = lifecycle.restore_company(slug)
        except lifecycle.LifecycleError as exc:
            return self.lifecycle_error(exc)
        return schemas.CompanyRead.model_validate(company)


# ── Модули компании ─────────────────────────────────────────────────────

class CompanyModulesView(CompaniesView):
    @read
    def get(self, request, slug: str):
        try:
            company = self.company_or_404(slug)
        except lifecycle.LifecycleError as exc:
            return self.lifecycle_error(exc)
        return [schemas.ModuleRead(**row) for row in module_service.list_modules(company)]


class CompanyModuleItemView(CompaniesView):
    @write("PATCH", body=schemas.ModulePatch)
    def patch(self, request, slug: str, app_label: str, data: schemas.ModulePatch):
        try:
            company = self.company_or_404(slug)
        except lifecycle.LifecycleError as exc:
            return self.lifecycle_error(exc)
        try:
            row = module_service.set_module(company, app_label,
                                            enabled=data.enabled, message=data.message)
        except module_service.UnknownModule as exc:
            return json_error(exc.detail, 422)
        except module_service.CoreModuleLocked as exc:
            return json_error(exc.detail, 409)
        return schemas.ModuleRead(**row)


# ── Участники компании ──────────────────────────────────────────────────

class CompanyMembershipsView(CompaniesView):
    @read
    def get(self, request, slug: str):
        try:
            company = self.company_or_404(slug)
        except lifecycle.LifecycleError as exc:
            return self.lifecycle_error(exc)
        return [schemas.MembershipRead(**row)
                for row in membership_service.list_memberships(company)]

    @write("POST", body=schemas.MembershipCreate)
    def post(self, request, slug: str, data: schemas.MembershipCreate):
        try:
            company = self.company_or_404(slug)
        except lifecycle.LifecycleError as exc:
            return self.lifecycle_error(exc)
        if get_user_brief(data.user_id) is None:
            return json_error(f"Пользователь {data.user_id} не найден", 422)
        created = membership_service.grant_membership(
            company, data.user_id, is_default=data.is_default,
        )
        row = next(m for m in membership_service.list_memberships(company)
                   if m["user_id"] == data.user_id)
        return JsonResponse(schemas.MembershipRead(**row).model_dump(mode="json"),
                            status=201 if created else 200)


class CompanyMembershipItemView(CompaniesView):
    @platform("DELETE")
    def delete(self, request, slug: str, user_id: int):
        denied = self.deny_unless_platform_admin()
        if denied is not None:
            return denied
        try:
            company = self.company_or_404(slug)
        except lifecycle.LifecycleError as exc:
            return self.lifecycle_error(exc)
        if user_id == request.token.user_id:
            # Запереть себя снаружи можно одним кликом, а вернуться — только
            # через company_grant в консоли.
            return JsonResponse({"detail": "Нельзя снять членство у себя",
                                 "code": "self_revoke"}, status=409)
        if not membership_service.revoke_membership(company, user_id):
            return json_error("Членства нет", 404)
        return HttpResponse(status=204)
