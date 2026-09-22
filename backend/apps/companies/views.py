"""HTTP-слой ``/api/companies/v1/*`` — план блока A, «Контракт API».

Стиль тот же, что в ``apps.access``: ``htqweb.http.ApiView``, ``api_view``
пометодно через ``method_decorator``.

**Гейты.** Чтение и правка реестра — ``api_view(module="companies", ...)``:
функции ``companies.registry/modules/memberships`` объявлены в
``access_functions.py`` аппки. Архив, восстановление и отзыв членства —
операции платформенного уровня (архив = 404 на весь трафик компании; отзыв
членства запирает человека снаружи), поэтому ``admin=True`` плюс явная
проверка ``is_superuser``, как у каталога ролей в ``apps.access``.

⚠️ ``api_view(module=…)`` считает уровень доступа в КОМПАНИИ ВЫЗЫВАЮЩЕГО
(``current_company_or_none()``) и ничего не знает про ``slug`` из URL — сам
по себе он не мешает компании A писать в строку компании B. Поэтому правка
компании (``CompanyItemView.patch``), переключение модуля
(``CompanyModuleItemView.patch``) и выдача членства
(``CompanyMembershipsView.post``) дополнительно зовут
``deny_unless_platform_admin`` — реестр компаний ведёт только платформенный
администратор (roadmap §5.A), несмотря на write-декоратор снаружи. Чтение
подресурсов одной компании (``CompanyModulesView.get``,
``CompanyMembershipsView.get``) по той же причине зовёт
``deny_unless_own_company``: видеть их может либо платформенный
администратор, либо сама компания.

**Заведения компании здесь нет** — намеренно: ``provision_company`` гонит
миграции четырёх аппок около минуты, ``gunicorn --timeout 60`` убьёт воркер
посреди DDL. Заведение — ``manage.py company_create``.
"""

from __future__ import annotations

from django.http import HttpResponse, JsonResponse
from django.utils.decorators import method_decorator

from apps.users.interface import get_user_brief
from htqweb.http import ApiView, api_view, json_error
from htqweb.tenancy.context import current_company_or_none

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

    def deny_unless_own_company(self, slug: str):
        """Подресурсы компании читает либо платформенный администратор, либо
        сама компания. Гейт ``api_view(module=…)`` считает уровень в КОМПАНИИ
        ВЫЗЫВАЮЩЕГО и про ``slug`` из URL ничего не знает — без этой сверки
        читатель реестра одной компании видел бы состав участников соседней.
        """
        if self.request.token.is_superuser:
            return None
        if slug == current_company_or_none():
            return None
        return json_error(
            "Подресурсы другой компании недоступны", 403,
        )

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
                slug=m.company.slug, subdomain=m.company.subdomain,
                name=m.company.name, kind=m.company.kind,
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
        """Переименование, смена ``kind`` и перепривязка родителя — операция
        платформенного уровня (roadmap §5.A): реестр компаний ведёт
        платформенный администратор. ``@write(...)`` считает уровень в
        компании ВЫЗЫВАЮЩЕГО, а не в ``slug`` из URL, поэтому сам по себе не
        мешает компании A переписать строку компании B — вторая проверка
        обязательна.
        """
        denied = self.deny_unless_platform_admin()
        if denied is not None:
            return denied
        kwargs = {"name": data.name, "kind": data.kind, "country": data.country,
                 "show_external_holders": data.show_external_holders}
        if "parent_slug" in data.model_fields_set:
            kwargs["parent_slug"] = data.parent_slug
        if "subdomain" in data.model_fields_set:
            # Ключ есть — ""/null снимают псевдоним; ключа нет — UNSET
            # (умолчание update_company), поле не трогается.
            kwargs["subdomain"] = data.subdomain
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
        """Список модулей одной компании. ``@read`` (``module="companies"``)
        считает уровень в компании ВЫЗЫВАЮЩЕГО и ничего не знает про ``slug``
        из URL, поэтому читатель с ролью в компании A мог бы этой же ручкой
        увидеть состояние модулей компании B — закрываем ``deny_unless_own_company``.
        """
        denied = self.deny_unless_own_company(slug)
        if denied is not None:
            return denied
        try:
            company = self.company_or_404(slug)
        except lifecycle.LifecycleError as exc:
            return self.lifecycle_error(exc)
        return [schemas.ModuleRead(**row) for row in module_service.list_modules(company)]


class CompanyModuleItemView(CompaniesView):
    @write("PATCH", body=schemas.ModulePatch)
    def patch(self, request, slug: str, app_label: str, data: schemas.ModulePatch):
        """Включить/выключить модуль компании — платформенная операция: тот же
        разрыв, что и у ``CompanyItemView.patch`` (``@write`` слеп к ``slug``
        из URL), только с последствием «выключить соседу целый домен».
        """
        denied = self.deny_unless_platform_admin()
        if denied is not None:
            return denied
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
        """Ростер участников одной компании — ``username``/``full_name``/
        ``email`` внутри. ``@read`` (``module="companies"``) считает уровень
        в компании ВЫЗЫВАЮЩЕГО и не смотрит на ``slug`` из URL, поэтому без
        ``deny_unless_own_company`` читатель реестра одной компании видел бы
        состав соседней.
        """
        denied = self.deny_unless_own_company(slug)
        if denied is not None:
            return denied
        try:
            company = self.company_or_404(slug)
        except lifecycle.LifecycleError as exc:
            return self.lifecycle_error(exc)
        return [schemas.MembershipRead(**row)
                for row in membership_service.list_memberships(company)]

    @write("POST", body=schemas.MembershipCreate)
    def post(self, request, slug: str, data: schemas.MembershipCreate):
        """Выдать членство — а с ним легитимный claim ``company`` и весь
        тенантный доступ компании. Платформенная операция по той же причине,
        что и ``CompanyItemView.patch``: ``@write`` слеп к ``slug`` из URL,
        поэтому без явной проверки владелец write в компании A мог бы впустить
        кого угодно в компанию B.
        """
        denied = self.deny_unless_platform_admin()
        if denied is not None:
            return denied
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


# ── Внешние держатели прав ──────────────────────────────────────────────

class CompanyExternalHoldersView(CompaniesView):
    """``GET companies/<slug>/external-holders`` — задача 7 блока C.

    Кто из компаний-предков сейчас держит права ЗДЕСЬ через обслуживающую
    должность (``apps.access.services.holders.external_holders``, за
    ``apps.access.interface`` — companies не видит внутренности access).

    Гейт — тот же ``deny_unless_own_company``, что и у ростера участников:
    своя компания либо платформенный администратор. Настройка
    ``Company.show_external_holders`` (решение заказчика 4) проверяется
    ПОСЛЕ гейта и отдаёт 403 с телом, а не пустой список — пустой список
    сказал бы «внешних держателей нет», а это неправда, когда их просто не
    показывают.
    """

    @read
    def get(self, request, slug: str):
        denied = self.deny_unless_own_company(slug)
        if denied is not None:
            return denied
        try:
            company = self.company_or_404(slug)
        except lifecycle.LifecycleError as exc:
            return self.lifecycle_error(exc)
        if not company.show_external_holders:
            return json_error(
                "Видимость держателей прав из вышестоящих компаний выключена "
                "для этой компании платформенным администратором", 403,
            )
        from apps.access import interface as access

        return [schemas.ExternalHolderRead(**row) for row in access.external_holders(slug)]
