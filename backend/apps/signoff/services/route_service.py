"""Настройка маршрутов: CRUD маршрутов, этапов и их согласующих.

Отделено от ``engine.py`` намеренно: там — исполнение (переходы, блокировки,
колбэки), здесь — редактирование конфигурации. Единственное, что их
связывает, — снимок этапов на запуске процесса, после которого правки
маршрута на идущее согласование уже не влияют.
"""

from __future__ import annotations

from contextlib import contextmanager

from django.db import IntegrityError, transaction
from django.http import Http404

from apps.signoff.models import (
    ApprovalRoute,
    ApprovalRouteStage,
    ApprovalRouteStageApprover,
)
from apps.signoff.services import conditions, registry
from apps.users import interface as users


class RouteConflict(Exception):
    """Нарушение уникальности или попытка сделать маршрут неисполнимым."""


@contextmanager
def conflict_as(message: str):
    """``IntegrityError`` → ``RouteConflict`` (409), не оставив за собой
    сломанную транзакцию.

    Вложенный ``atomic`` (savepoint) обязателен: в Postgres IntegrityError
    переводит текущую транзакцию в aborted, и без точки сохранения поймать
    ошибку и продолжить нельзя. Тот же приём, что в
    ``apps/contracts/services/reference_service.py``.
    """
    try:
        with transaction.atomic():
            yield
    except IntegrityError as exc:
        raise RouteConflict(message) from exc


# ── Маршруты ────────────────────────────────────────────────────────────

def list_routes(*, subject_type: str | None = None,
                is_active: bool | None = None) -> list[ApprovalRoute]:
    query = ApprovalRoute.objects.prefetch_related("stages__approvers")
    if subject_type is not None:
        query = query.filter(subject_type=subject_type)
    if is_active is not None:
        query = query.filter(is_active=is_active)
    return list(query)


def get_route_or_404(route_id: int) -> ApprovalRoute:
    route = (ApprovalRoute.objects.prefetch_related("stages__approvers")
             .filter(pk=route_id).first())
    if route is None:
        raise Http404("Маршрут не найден")
    return route


def create_route(*, subject_type: str, name: str,
                 is_active: bool = True) -> ApprovalRoute:
    # Тип должен быть зарегистрирован: маршрут на незарегистрированный тип
    # никогда не запустится (engine.start падает на get_subject), а
    # обнаружится это только в момент отправки на согласование.
    registry.get_subject(subject_type)

    with conflict_as(
        f"У типа «{subject_type}» уже есть активный маршрут — "
        f"деактивируйте его или правьте существующий"
    ):
        return ApprovalRoute.objects.create(
            subject_type=subject_type, name=name, is_active=is_active)


def update_route(route_id: int, **fields) -> ApprovalRoute:
    route = get_route_or_404(route_id)
    changed = [key for key, value in fields.items() if value is not None]
    for key in changed:
        setattr(route, key, fields[key])
    if changed:
        with conflict_as(
            f"У типа «{route.subject_type}» уже есть другой активный маршрут"
        ):
            route.save()
    return route


def delete_route(route_id: int) -> None:
    """Удалить маршрут вместе с этапами.

    Идущие процессы не задеваются: их этапы — снимок, а ``route_id`` на
    процессе хранится голым числом без FK именно для того, чтобы удаление
    настройки не уносило историю согласований.
    """
    get_route_or_404(route_id).delete()


# ── Этапы ───────────────────────────────────────────────────────────────

def get_stage_or_404(stage_id: int) -> ApprovalRouteStage:
    stage = (ApprovalRouteStage.objects.select_related("route")
             .prefetch_related("approvers").filter(pk=stage_id).first())
    if stage is None:
        raise Http404("Этап маршрута не найден")
    return stage


@transaction.atomic
def add_stage(route_id: int, *, order: int, name: str, quorum: str,
              approver_ids: list[int], condition=None,
              is_fallback: bool = False) -> ApprovalRouteStage:
    route = get_route_or_404(route_id)
    _check_approvers_exist(approver_ids)
    condition = _check_condition(route.subject_type, condition, is_fallback)

    stage = ApprovalRouteStage.objects.create(
        route=route, order=order, name=name, quorum=quorum,
        condition=condition, is_fallback=is_fallback)
    _set_approvers(stage, approver_ids)
    return stage


@transaction.atomic
def update_stage(stage_id: int, **fields) -> ApprovalRouteStage:
    stage = get_stage_or_404(stage_id)

    approver_ids = fields.pop("approver_ids", None)
    if approver_ids is not None:
        if not approver_ids:
            # Этап без согласующих не исполнится (engine._resolve_stages) —
            # отказываем здесь, а не через час на отправке заявки.
            raise RouteConflict(
                f"В этапе «{stage.name}» должен остаться хотя бы один согласующий")
        _check_approvers_exist(approver_ids)
        _set_approvers(stage, approver_ids)

    # Условие и «иначе» проверяются вместе, даже когда меняется только одно
    # из них: их несочетаемость — свойство ПАРЫ, и проверить пришедшее поле
    # против сохранённого второго иначе невозможно.
    if "condition" in fields or "is_fallback" in fields:
        condition = fields.get("condition", stage.condition)
        is_fallback = fields.get("is_fallback", stage.is_fallback)
        if is_fallback is None:
            is_fallback = stage.is_fallback
        fields["condition"] = _check_condition(
            stage.route.subject_type, condition, is_fallback)
        fields["is_fallback"] = is_fallback

    changed = [key for key, value in fields.items() if value is not None]
    for key in changed:
        setattr(stage, key, fields[key])
    if changed:
        stage.save()
    return stage


@transaction.atomic
def delete_stage(stage_id: int) -> None:
    delete_protected_last_stage(get_stage_or_404(stage_id))


def delete_protected_last_stage(stage: ApprovalRouteStage) -> None:
    """Последний этап маршрута удалить нельзя.

    Маршрут без этапов проходит все проверки настройки и падает только на
    запуске процесса — то есть в руках пользователя, который к настройке
    отношения не имеет.
    """
    if stage.route.stages.count() <= 1:
        raise RouteConflict(
            "Это последний этап маршрута — удалите сам маршрут или добавьте "
            "другой этап прежде, чем убирать этот"
        )
    stage.delete()


def _set_approvers(stage: ApprovalRouteStage, user_ids: list[int]) -> None:
    """Заменить список согласующих этапа.

    Полная замена, а не вычисление разницы: список короткий, а разностная
    правка здесь означала бы лишний код ради экономии двух запросов.
    """
    stage.approvers.all().delete()
    ApprovalRouteStageApprover.objects.bulk_create([
        ApprovalRouteStageApprover(stage=stage, user_id=user_id)
        for user_id in dict.fromkeys(user_ids)  # порядок сохраняем, дубли убираем
    ])


def _check_condition(subject_type: str, condition, is_fallback: bool) -> list:
    """Проверить условие этапа против схемы фактов его типа.

    Та же роль, что у ``_check_approvers_exist``: опечатку в настройке ловим
    у того, кто настраивает. Иначе условие про несуществующее поле дожило бы
    до отправки заявки и превратилось в отказ на ровном месте у пользователя,
    который к маршруту отношения не имеет.
    """
    if is_fallback and condition:
        # Сочетание нечитаемо: «иначе» означает «когда не сошлось ничто
        # другое», и собственное условие ему противоречит. Молча предпочесть
        # одно другому значило бы исполнить не то, что видит администратор.
        raise RouteConflict(
            "Этап «иначе» не может иметь собственного условия — уберите одно из двух")

    # Выходим ДО обращения к схеме: у безусловного этапа проверять нечего, а
    # ``fields_for`` — это вызов чужого кода, ходящего в чужую БД. Иначе тип
    # со сломанным ``fact_fields()`` перестал бы принимать и обычные этапы,
    # которым ветвление вообще не нужно.
    if not condition:
        return []

    try:
        return conditions.validate(condition, registry.fields_for(subject_type))
    except conditions.ConditionError as exc:
        raise RouteConflict(str(exc)) from exc


def coverage_gaps(route: ApprovalRoute) -> list[dict]:
    """Значения справочников, под которые в маршруте не заведено ветки.

    Предупреждение редактору, а не запрет: маршрут с дырой валиден до тех
    пор, пока в неё не попадёт объект, — и упадёт он тогда уже у
    пользователя (``engine._select_stages``). Показать дыру администратору
    заранее дешевле, чем ловить её отправкой заявки.
    """
    try:
        fields = registry.fields_for(route.subject_type)
    except (registry.UnknownSubject, conditions.ConditionError):
        # Тип снят с регистрации или его схема сломана — это забота другого
        # места; подсказка на этом падать не должна.
        return []
    return conditions.coverage_gaps(route.stages.all(), fields)


def _check_approvers_exist(user_ids: list[int]) -> None:
    """Все ли перечисленные id — существующие пользователи.

    Проверяется на настройке: несуществующий id иначе дожил бы до запуска
    процесса и превратился в «на этапе не осталось активных согласующих» —
    сообщение, по которому не догадаться, что в маршруте просто опечатка.
    """
    known = {row["id"] for row in users.get_users_brief(user_ids)}
    unknown = [user_id for user_id in user_ids if user_id not in known]
    if unknown:
        raise RouteConflict(
            "Не найдены пользователи: " + ", ".join(str(x) for x in unknown))


# ── Представление ───────────────────────────────────────────────────────

def serialize_route(route: ApprovalRoute, *,
                    names: dict[int, dict] | None = None,
                    gaps: bool = False) -> dict:
    """``gaps=True`` добавляет подсказку о непокрытых значениях справочника.

    Не по умолчанию: считать её — значит сходить за схемой фактов в
    предметную аппку, а в списке маршрутов это лишний поход на каждую строку.
    Нужна она ровно в редакторе одного маршрута.
    """
    stages = list(route.stages.all())
    if names is None:
        names = _name_map([approver.user_id
                           for stage in stages
                           for approver in stage.approvers.all()])
    card = {
        "id": route.pk,
        "subject_type": route.subject_type,
        "name": route.name,
        "is_active": route.is_active,
        "created_at": route.created_at,
        "updated_at": route.updated_at,
        "stages": [serialize_stage(stage, names=names) for stage in stages],
    }
    if gaps:
        card["coverage_gaps"] = coverage_gaps(route)
    return card


def serialize_stage(stage: ApprovalRouteStage, *,
                    names: dict[int, dict] | None = None) -> dict:
    approver_ids = [approver.user_id for approver in stage.approvers.all()]
    if names is None:
        names = _name_map(approver_ids)
    return {
        "id": stage.pk,
        "order": stage.order,
        "name": stage.name,
        "quorum": stage.quorum,
        "condition": stage.condition or [],
        "is_fallback": stage.is_fallback,
        "approvers": [
            {
                "user_id": user_id,
                "full_name": names.get(user_id, {}).get("full_name", ""),
                # Отсутствующий в briefs id — удалённый пользователь; для
                # настройки это то же самое, что неактивный: маршрут с ним
                # не поедет, и в интерфейсе он должен быть виден красным.
                "is_active": names.get(user_id, {}).get("is_active", False),
            }
            for user_id in approver_ids
        ],
    }


def _name_map(user_ids) -> dict[int, dict]:
    """``{user_id: brief}`` одним запросом в соседа.

    Имена разворачиваются пачкой на весь маршрут, а не по согласующему:
    маршрут из пяти этапов иначе дал бы пять походов в apps.users.
    """
    ids = list(dict.fromkeys(user_ids))
    if not ids:
        return {}
    return {row["id"]: row for row in users.get_users_brief(ids)}
