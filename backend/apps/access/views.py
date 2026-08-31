"""HTTP-слой ``/api/access/v1/*`` — class-based вьюхи (контракт: спека §4).

Стиль тот же, что в ``apps.contracts`` и ``apps.signoff``: ``htqweb.http.ApiView``,
``api_view`` навешивается ПОМЕТОДНО через ``method_decorator``. Пометодно — не
из вкусовых соображений: режим авторизации у методов одного URL разный, а
``api_view`` связывает ровно один режим с одной функцией.

**Права.** Каталог ролей общий для всех компаний, поэтому его правка — операция
платформенного уровня и требует ``is_superuser``, а не общего админского флага
``is_elevated`` (который включает ``is_staff``). Разница существенная: правка
роли меняет доступ во ВСЕХ компаниях сразу, и обратной силы у ошибки нет
(спека §4.1, риск 2). Привязки же — ролей к должности и личных назначений —
операции внутри одной компании и гейтятся обычным ``admin=True``.

**Компания берётся из контекста запроса**, а не из тела и не из query-параметра:
иначе слаг компании становится значением, которое можно подставить, и изоляция
превращается в вежливую просьбу.
"""

from __future__ import annotations

from django.http import JsonResponse
from django.utils.decorators import method_decorator

from htqweb.http import ApiView, api_view, json_error
from htqweb.tenancy.context import current_company_or_none

from . import schemas
from .models import Role
from apps.access import registry
from .services import assignment, catalog, holders as holders_svc, resolve
from .services import hierarchy
from .services.errors import (
    DepthNotApplicable,
    RoleConflict,
    RoleInUse,
    RoleIsSystem,
    ScopeInvalid,
    SystemRoleCodeLocked,
    UnknownModule,
    UnknownRole,
)

# 422 — тело корректно по форме, но противоречит состоянию каталога.
# Отдельно от 409: «нет такой роли» и «такого модуля не существует» — это
# неверные ЗНАЧЕНИЯ, а не конфликт с состоянием данных.
INVALID = (RoleConflict, UnknownModule, UnknownRole, ScopeInvalid,
           DepthNotApplicable)

read = method_decorator(api_view(methods=("GET",), auth="jwt"))


def write(method: str, body=None, status: int = 200, admin: bool = True):
    return method_decorator(api_view(methods=(method,), auth="jwt",
                                     body=body, status=status, admin=admin))


class AccessView(ApiView):
    """База вьюх домена: контекст компании и гейт платформенного админа."""

    @property
    def company(self) -> str | None:
        return current_company_or_none()

    def company_or_404(self) -> str:
        """Привязки существуют только внутри компании.

        Без контекста компании ресурса нет — это 404, а не 400: запрос
        синтаксически безупречен, просто адресует то, чего вне компании не
        существует.
        """
        from django.http import Http404

        company = self.company
        if company is None:
            raise Http404("Компания не определена")
        return company

    def deny_unless_platform_admin(self):
        if not self.request.token.is_superuser:
            return json_error(
                "Каталог ролей общий для всех компаний: править его может "
                "только платформенный администратор",
                403,
            )
        return None


class FunctionsView(AccessView):
    """``GET functions`` — реестр функций деревом.

    Читать может любой вошедший: это справочник экранов платформы, а не данные.
    Без него редактор ролей нечем нарисовать — матрица прав строится по нему.
    """

    @read
    def get(self, request):
        from apps.access import depth

        return {
            "tree": registry.tree(),
            "pages": registry.page_nodes(),
            "flags": [{"key": flag, "title": depth.FLAG_TITLES[flag]}
                      for flag in depth.FLAGS],
            "presets": [{"key": name, "title": depth.PRESET_TITLES[name],
                         "flags": sorted(depth.PRESETS[name])}
                        for name in depth.PRESETS],
        }


class RoleCollectionView(AccessView):
    """``GET|POST roles`` — плоский каталог, общий для всех компаний (§4.1)."""

    @read
    def get(self, request):
        return [schemas.RoleRead.model_validate(row)
                for row in Role.objects.all()]

    @write("POST", body=schemas.RoleIn, status=201, admin=False)
    def post(self, request, data: schemas.RoleIn):
        if (denied := self.deny_unless_platform_admin()):
            return denied
        try:
            role = catalog.create_role(data.code, data.title)
        except INVALID as exc:
            return json_error(str(exc) or "invalid", 422)
        return schemas.RoleRead.model_validate(role)


class RoleItemView(AccessView):
    """``PATCH|DELETE roles/<id>``."""

    @write("PATCH", body=schemas.RolePatchIn, admin=False)
    def patch(self, request, role_id: int, data: schemas.RolePatchIn):
        if (denied := self.deny_unless_platform_admin()):
            return denied
        try:
            role = catalog.rename_role(role_id, title=data.title, code=data.code)
        except Role.DoesNotExist:
            return json_error("Роль не найдена", 404)
        except SystemRoleCodeLocked:
            return json_error(
                "Код системной роли менять нельзя: по нему её находят миграции", 409)
        except INVALID as exc:
            return json_error(str(exc) or "invalid", 422)
        return schemas.RoleRead.model_validate(role)

    @write("DELETE", admin=False)
    def delete(self, request, role_id: int):
        if (denied := self.deny_unless_platform_admin()):
            return denied
        try:
            catalog.delete_role(role_id)
        except Role.DoesNotExist:
            return json_error("Роль не найдена", 404)
        except RoleInUse as exc:
            # Тело шире обычного конверта намеренно: интерфейсу нужно показать,
            # у СКОЛЬКИХ должностей и людей роль отнимется, иначе отказ
            # выглядит произволом.
            return JsonResponse({"detail": "in_use", "positions": exc.positions,
                                 "users": exc.users}, status=409)
        except RoleIsSystem:
            return json_error("Служебную роль удалить нельзя", 409)
        return {"ok": True}


class RoleHoldersView(AccessView):
    """``GET roles/<id>/holders`` — у кого сейчас эта роль.

    Нужна диалогу удаления. Отказ с одним лишь числом («назначена трём
    должностям») не говорит, к кому идти: снять роль по такому ответу нельзя,
    придётся искать вручную по всем компаниям.
    """

    @read
    def get(self, request, role_id: int):
        return holders_svc.holders(role_id)


class RoleCopyView(AccessView):
    """``POST roles/<id>/copy`` — новая роль с той же глубиной.

    Отдельная ручка, а не «создать и потом скопировать права»: между двумя
    запросами роль существовала бы пустой, и прерывание оставило бы в каталоге
    роль без единого права — от настоящей она неотличима, а даёт ноль.
    """

    @write("POST", body=schemas.RoleIn, status=201, admin=False)
    def post(self, request, role_id: int, data: schemas.RoleIn):
        if (denied := self.deny_unless_platform_admin()):
            return denied
        try:
            clone = catalog.copy_role(role_id, data.code, data.title)
        except Role.DoesNotExist:
            return json_error("Роль не найдена", 404)
        except INVALID as exc:
            return json_error(str(exc) or "invalid", 422)
        return schemas.RoleRead.model_validate(clone)


class RolePermissionsView(AccessView):
    """``GET|PUT roles/<id>/permissions`` — набор заменяется целиком (§4.2)."""

    @read
    def get(self, request, role_id: int):
        return catalog.permissions_of(role_id)

    @write("PUT", body=schemas.PermissionsIn, admin=False)
    def put(self, request, role_id: int, data: schemas.PermissionsIn):
        if (denied := self.deny_unless_platform_admin()):
            return denied
        try:
            catalog.set_permissions(role_id, [i.model_dump() for i in data.root])
        except INVALID as exc:
            return json_error(str(exc) or "invalid", 422)
        return catalog.permissions_of(role_id)


class PositionRolesView(AccessView):
    """``GET|PUT positions/<id>/roles`` — штатный путь выдачи прав (§4.3)."""

    def position_or_404(self, position_id: int) -> None:
        """Должность проверяется через ``apps.hr.interface``, а не запросом.

        Модели HR аппка доступа не импортирует; кроме того, должность лежит в
        схеме компании, и «своя ли она» решает контекст, а не сравнение id.
        """
        from django.http import Http404

        from apps.hr import interface as hr

        if not hr.get_positions_brief([position_id]):
            raise Http404("Должность не найдена в этой компании")

    @read
    def get(self, request, position_id: int):
        company = self.company_or_404()
        self.position_or_404(position_id)
        return assignment.position_roles(company, position_id)

    @write("PUT", body=schemas.PositionRolesIn)
    def put(self, request, position_id: int, data: schemas.PositionRolesIn):
        company = self.company_or_404()
        self.position_or_404(position_id)
        try:
            assignment.set_position_roles(company, position_id, data.role_ids)
        except INVALID as exc:
            return json_error(str(exc) or "invalid", 422)
        return assignment.position_roles(company, position_id)


class UserAssignmentsView(AccessView):
    """``GET|PUT assignments/<user_id>`` — исключительный путь (§4.4)."""

    @read
    def get(self, request, user_id: int):
        return assignment.user_assignments(self.company_or_404(), user_id)

    @write("PUT", body=schemas.AssignmentsIn)
    def put(self, request, user_id: int, data: schemas.AssignmentsIn):
        company = self.company_or_404()
        try:
            assignment.set_user_assignments(
                company, user_id, [i.model_dump() for i in data.root])
        except INVALID as exc:
            return json_error(str(exc) or "invalid", 422)
        return assignment.user_assignments(company, user_id)


class MeView(AccessView):
    """``GET me`` — права текущего пользователя (§4.5).

    Без контекста компании отвечает пустой картой, а НЕ ошибкой: это штатный
    переходный режим подпроекта 1, а не сбой.
    """

    @read
    def get(self, request):
        company = self.company
        return schemas.MeRead(
            company=company,
            permissions=resolve.permissions_for(request.token, company),
            depth=resolve.depth_map(request.token, company),
            hidden_pages=[
                row["route"] for row in registry.page_nodes()
                if resolve.page_hidden(request.token, row["route"], company)
            ],
            subordinate_companies=hierarchy.subordinate_companies(
                request.token, company),
        )
