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
    ApprovalRouteStageRole,
    ApproverKind,
)
from apps.signoff.services import conditions, registry
from apps.hr import interface as hr
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
                is_active: bool | None = None,
                scope: str | None = None) -> list[ApprovalRoute]:
    query = ApprovalRoute.objects.prefetch_related("stages__roles")
    if subject_type is not None:
        query = query.filter(subject_type=subject_type)
    if is_active is not None:
        query = query.filter(is_active=is_active)
    if scope is not None:
        query = query.filter(scope=scope)
    return list(query)


def get_route_or_404(route_id: int) -> ApprovalRoute:
    route = (ApprovalRoute.objects.prefetch_related("stages__roles")
             .filter(pk=route_id).first())
    if route is None:
        raise Http404("Маршрут не найден")
    return route


def create_route(*, subject_type: str, name: str,
                 is_active: bool = True, scope: str = "") -> ApprovalRoute:
    # Тип должен быть зарегистрирован: маршрут на незарегистрированный тип
    # никогда не запустится (engine.start падает на get_subject), а
    # обнаружится это только в момент отправки на согласование.
    subject = registry.get_subject(subject_type)
    scope = (scope or "").strip()
    if scope and subject.scope_of is None:
        # Тип без областей никогда не спросит маршрут по области — такой
        # маршрут молча не сработал бы ни для одного объекта.
        raise RouteConflict(
            f"Тип «{subject.label}» не делится на области — маршрут задаётся "
            f"на весь тип")

    where = f"«{subject_type}» ({scope})" if scope else f"«{subject_type}»"
    with conflict_as(
        f"У типа {where} уже есть активный маршрут — "
        f"деактивируйте его или правьте существующий"
    ):
        return ApprovalRoute.objects.create(
            subject_type=subject_type, scope=scope, name=name,
            is_active=is_active)


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
             .prefetch_related("roles").filter(pk=stage_id).first())
    if stage is None:
        raise Http404("Этап маршрута не найден")
    return stage


@transaction.atomic
def add_stage(route_id: int, *, order: int, name: str, quorum: str,
              position_ids: list[int], condition=None,
              is_fallback: bool = False,
              approver_kind: str = ApproverKind.POSITION,
              user_ids: list[int] | None = None,
              approver_key: str = "",
              requires_attachment: bool = False,
              requires_comment: bool = False,
              requirement_key: str = "") -> ApprovalRouteStage:
    route = get_route_or_404(route_id)
    picked = _check_approver_kind(
        approver_kind, position_ids, user_ids or [], approver_key or "",
        subject_type=route.subject_type, scope=route.scope, stage_name=name)
    condition = _check_condition(route.subject_type, condition, is_fallback,
                                 scope=route.scope)
    requirement_key = _check_requirement_key(
        requirement_key or "", subject_type=route.subject_type,
        scope=route.scope, stage_name=name)

    stage = ApprovalRouteStage.objects.create(
        route=route, order=order, name=name, quorum=quorum,
        condition=condition, is_fallback=is_fallback,
        approver_kind=approver_kind,
        user_ids=picked["user_ids"], approver_key=picked["approver_key"],
        requires_attachment=requires_attachment,
        requires_comment=requires_comment,
        requirement_key=requirement_key)
    _set_roles(stage, picked["position_ids"])
    return stage


@transaction.atomic
def update_stage(stage_id: int, **fields) -> ApprovalRouteStage:
    stage = get_stage_or_404(stage_id)

    position_ids = fields.pop("position_ids", None)
    user_ids = fields.pop("user_ids", None)
    approver_key = fields.pop("approver_key", None)

    # Вид согласующих и его настройка (должности / люди / ключ объекта) —
    # свойство ОДНОГО набора, поэтому пересматриваются вместе, даже когда
    # пришла только часть (тот же случай, что у condition/is_fallback ниже).
    # Иначе переключение этапа на инициатора оставило бы в нём названных
    # поимённо людей, которых движок игнорирует, а редактор не показывает.
    touched = (any(value is not None for value in (position_ids, user_ids, approver_key))
               or "approver_kind" in fields)
    if touched:
        kind = fields.get("approver_kind") or stage.approver_kind
        kind_changed = kind != stage.approver_kind
        # Не присланное поле берём из этапа только если вид не менялся:
        # при смене вида прежняя настройка к новому виду не относится.
        effective_positions = (position_ids if position_ids is not None
                               else ([] if kind_changed
                                     else [row.position_id for row in stage.roles.all()]))
        effective_users = (user_ids if user_ids is not None
                           else ([] if kind_changed else list(stage.user_ids or [])))
        effective_key = (approver_key if approver_key is not None
                         else ("" if kind_changed else stage.approver_key))
        picked = _check_approver_kind(
            kind, effective_positions, effective_users, effective_key,
            subject_type=stage.route.subject_type, scope=stage.route.scope,
            stage_name=stage.name)
        _set_roles(stage, picked["position_ids"])
        fields["user_ids"] = picked["user_ids"]
        fields["approver_key"] = picked["approver_key"]

    # Условие и «иначе» проверяются вместе, даже когда меняется только одно
    # из них: их несочетаемость — свойство ПАРЫ, и проверить пришедшее поле
    # против сохранённого второго иначе невозможно.
    if "condition" in fields or "is_fallback" in fields:
        condition = fields.get("condition", stage.condition)
        is_fallback = fields.get("is_fallback", stage.is_fallback)
        if is_fallback is None:
            is_fallback = stage.is_fallback
        fields["condition"] = _check_condition(
            stage.route.subject_type, condition, is_fallback,
            scope=stage.route.scope)
        fields["is_fallback"] = is_fallback

    if fields.get("requirement_key") is not None:
        fields["requirement_key"] = _check_requirement_key(
            fields["requirement_key"], subject_type=stage.route.subject_type,
            scope=stage.route.scope, stage_name=fields.get("name") or stage.name)

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


def _set_roles(stage: ApprovalRouteStage, position_ids: list[int]) -> None:
    """Заменить список HR-должностей согласующих этапа.

    Полная замена, а не вычисление разницы: список короткий, а разностная
    правка здесь означала бы лишний код ради экономии двух запросов.
    """
    stage.roles.all().delete()
    ApprovalRouteStageRole.objects.bulk_create([
        ApprovalRouteStageRole(stage=stage, position_id=position_id)
        for position_id in dict.fromkeys(position_ids)
    ])


def _check_requirement_key(key: str, *, subject_type: str, scope: str,
                           stage_name: str) -> str:
    """Ключ «этап требует от объекта» должен быть из тех, что объявила
    предметная аппка, — иначе на решении его будет не по чему проверить, и
    этап либо зависнет, либо пройдёт мимо требования. Отказываем на
    настройке."""
    key = (key or "").strip()
    if not key:
        return ""
    allowed = {row["key"]: row["label"]
               for row in registry.requirement_fields_for(subject_type, scope)}
    if not allowed:
        raise RouteConflict(
            f"Тип «{subject_type}» не объявляет требований к объекту — "
            f"этап «{stage_name}» не может их ставить")
    if key not in allowed:
        raise RouteConflict(
            f"На этапе «{stage_name}» требование «{key}» неизвестно; "
            f"доступны: " + ", ".join(sorted(allowed)))
    return key


def _check_approver_kind(approver_kind: str, position_ids: list[int],
                         user_ids: list[int], approver_key: str, *,
                         subject_type: str, scope: str, stage_name: str) -> dict:
    """Совместимость вида согласующих с его настройкой.

    Возвращает, что сохранить: ``{position_ids, user_ids, approver_key}`` —
    у каждого вида заполнено ровно своё, остальное пусто. Настройка чужого
    вида (должности у инициатора, люди у этапа «по должности») — то, что
    движок исполнил бы не так, как оно читается (``engine._approver_ids``);
    отказываем на настройке, а не гадаем за администратора.
    """
    kind = approver_kind
    label = dict(ApproverKind.choices).get(kind, kind)
    foreign = []
    if kind != ApproverKind.POSITION and position_ids:
        foreign.append("должности")
    if kind != ApproverKind.USERS and user_ids:
        foreign.append("список сотрудников")
    if kind != ApproverKind.SUBJECT and approver_key:
        foreign.append("ключ объекта")
    if foreign:
        raise RouteConflict(
            f"На этапе «{stage_name}» вид согласующих — «{label}»: "
            + " и ".join(foreign) + " к нему не относятся, уберите их")

    if kind == ApproverKind.POSITION:
        if not position_ids:
            # Этап без должностей не исполнится (engine._approver_ids) —
            # отказываем здесь, а не через час на отправке заявки.
            raise RouteConflict(
                f"В этапе «{stage_name}» должна остаться хотя бы одна должность")
        _check_positions_exist(position_ids)
        return {"position_ids": list(dict.fromkeys(position_ids)),
                "user_ids": [], "approver_key": ""}
    if kind == ApproverKind.USERS:
        if not user_ids:
            raise RouteConflict(
                f"На этапе «{stage_name}» не назван ни один согласующий")
        _check_users_active(user_ids, stage_name=stage_name)
        return {"position_ids": [], "user_ids": [int(x) for x in dict.fromkeys(user_ids)],
                "approver_key": ""}
    if kind == ApproverKind.SUBJECT:
        allowed = {row["key"]: row["label"]
                   for row in registry.approver_fields_for(subject_type, scope)}
        if not allowed:
            raise RouteConflict(
                f"Тип «{subject_type}» не умеет назначать согласующих сам — "
                f"выберите другой вид этапа")
        if approver_key not in allowed:
            raise RouteConflict(
                f"На этапе «{stage_name}» ключ согласующих «{approver_key}» "
                f"неизвестен; доступны: " + ", ".join(sorted(allowed)))
        return {"position_ids": [], "user_ids": [], "approver_key": approver_key}
    # INITIATOR: настройки нет по определению.
    return {"position_ids": [], "user_ids": [], "approver_key": ""}


def _check_users_active(user_ids: list[int], *, stage_name: str) -> None:
    """Названные поимённо согласующие существуют и активны.

    Проверяется на настройке по той же причине, что и должности: иначе
    уволенный сотрудник в маршруте всплыл бы «неактивным согласующим» на
    отправке заявки, у человека, который к маршруту отношения не имеет.
    """
    briefs = {row["id"]: row for row in users.get_users_brief(list(user_ids))}
    bad = [str(uid) for uid in user_ids
           if uid not in briefs or not briefs[uid].get("is_active")]
    if bad:
        raise RouteConflict(
            f"На этапе «{stage_name}» есть неизвестные или неактивные "
            f"согласующие: " + ", ".join(bad))


def _check_condition(subject_type: str, condition, is_fallback: bool,
                     scope: str = "") -> list:
    """Проверить условие этапа против схемы фактов его типа.

    Та же роль, что у ``_check_positions_exist``: опечатку в настройке ловим
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
        return conditions.validate(condition,
                                   registry.fields_for(subject_type, scope))
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
        fields = registry.fields_for(route.subject_type, route.scope)
    except (registry.UnknownSubject, conditions.ConditionError):
        # Тип снят с регистрации или его схема сломана — это забота другого
        # места; подсказка на этом падать не должна.
        return []
    return conditions.coverage_gaps(route.stages.all(), fields)


def initiator_stage_not_last(route: ApprovalRoute) -> bool:
    """Стоит ли этап подписи инициатора НЕ в последней группе маршрута.

    Предупреждение, а не запрет — по тому же принципу, что ``coverage_gaps``,
    и по вполне практической причине: запрет означал бы, что после этапа
    подписи в маршрут нельзя добавить ни одного этапа, то есть любая
    последующая правка требовала бы сначала переставить подпись. Такой
    редактор чинят обходом, а не пользуются им.

    Смысл же предупреждения в том, что «подпись автора» задумана как ФИНАЛ:
    движок завершает процесс, когда пройдена группа с наибольшим ``order``
    (``engine._advance``), и этап, оказавшийся не последним, тихо превращается
    из подписи в промежуточное подтверждение.

    Считается по маршруту, а не по процессу: в процессе последняя группа
    зависит от сработавших веток, и там этот вопрос имеет другой ответ на
    каждый объект.
    """
    orders = [stage.order for stage in route.stages.all()]
    if not orders:
        return False
    last = max(orders)
    return any(stage.approver_kind == ApproverKind.INITIATOR
               and stage.order != last
               for stage in route.stages.all())


def _check_positions_exist(position_ids: list[int]) -> None:
    """Все ли перечисленные id — существующие HR-должности.

    Проверяется на настройке: несуществующий id иначе дожил бы до запуска
    процесса и превратился в «на этапе не осталось активных согласующих» —
    сообщение, по которому не догадаться, что в маршруте просто опечатка.
    """
    known = {row["id"] for row in hr.get_positions_brief(position_ids)}
    unknown = [position_id for position_id in position_ids if position_id not in known]
    if unknown:
        raise RouteConflict(
            "Не найдены должности: " + ", ".join(str(x) for x in unknown))


# ── Представление ───────────────────────────────────────────────────────

def serialize_route(route: ApprovalRoute, *,
                    roles: dict[int, dict] | None = None,
                    gaps: bool = False) -> dict:
    """``gaps=True`` добавляет подсказку о непокрытых значениях справочника.

    Не по умолчанию: считать её — значит сходить за схемой фактов в
    предметную аппку, а в списке маршрутов это лишний поход на каждую строку.
    Нужна она ровно в редакторе одного маршрута.
    """
    stages = list(route.stages.all())
    if roles is None:
        roles = _role_map([role.position_id
                           for stage in stages
                           for role in stage.roles.all()])
    people = _user_map([uid for stage in stages for uid in (stage.user_ids or [])])
    keys = _approver_key_labels(route)
    requirements = _requirement_key_labels(route)
    card = {
        "id": route.pk,
        "subject_type": route.subject_type,
        "scope": route.scope,
        "scope_label": registry.scope_label(route.subject_type, route.scope),
        "name": route.name,
        "is_active": route.is_active,
        "created_at": route.created_at,
        "updated_at": route.updated_at,
        "stages": [serialize_stage(stage, roles=roles, people=people, keys=keys,
                                   requirements=requirements)
                   for stage in stages],
    }
    if gaps:
        card["coverage_gaps"] = coverage_gaps(route)
        card["initiator_stage_not_last"] = initiator_stage_not_last(route)
        # Редактору одного маршрута нужна и схема его области: по каким
        # фактам ветвить и какие ключи объекта предлагать этапу «назначает
        # объект». В списке маршрутов это лишний поход в чужую аппку.
        card["fields"] = _safe_fields(route)
        card["approver_fields"] = [{"key": key, "label": label}
                                   for key, label in keys.items()]
        card["requirement_fields"] = [{"key": key, "label": label}
                                      for key, label in requirements.items()]
    return card


def _safe_fields(route: ApprovalRoute) -> list[dict]:
    try:
        return registry.fields_for(route.subject_type, route.scope)
    except Exception:
        return []


def _approver_key_labels(route: ApprovalRoute) -> dict[str, str]:
    """``{key: label}`` ключей «назначает объект» для области маршрута —
    оформление, поэтому сломанный колбэк аппки даёт пустой словарь."""
    try:
        return {row["key"]: row["label"]
                for row in registry.approver_fields_for(route.subject_type, route.scope)}
    except Exception:
        return {}


def _requirement_key_labels(route: ApprovalRoute) -> dict[str, str]:
    """``{key: label}`` требований к объекту для области маршрута —
    оформление, как ``_approver_key_labels``."""
    try:
        return {row["key"]: row["label"]
                for row in registry.requirement_fields_for(route.subject_type,
                                                           route.scope)}
    except Exception:
        return {}


def serialize_stage(stage: ApprovalRouteStage, *,
                    roles: dict[int, dict] | None = None,
                    people: dict[int, dict] | None = None,
                    keys: dict[str, str] | None = None,
                    requirements: dict[str, str] | None = None) -> dict:
    position_ids = [role.position_id for role in stage.roles.all()]
    if roles is None:
        roles = _role_map(position_ids)
    user_ids = [int(uid) for uid in (stage.user_ids or [])]
    if people is None:
        people = _user_map(user_ids)
    if keys is None:
        keys = _approver_key_labels(stage.route)
    if requirements is None:
        requirements = _requirement_key_labels(stage.route)
    return {
        "id": stage.pk,
        "order": stage.order,
        "name": stage.name,
        "quorum": stage.quorum,
        "condition": stage.condition or [],
        "is_fallback": stage.is_fallback,
        "approver_kind": stage.approver_kind,
        "requires_attachment": stage.requires_attachment,
        "requires_comment": stage.requires_comment,
        "user_ids": user_ids,
        "users": [
            {
                "user_id": user_id,
                "full_name": people.get(user_id, {}).get("full_name", ""),
                "is_active": bool(people.get(user_id, {}).get("is_active", False)),
            }
            for user_id in user_ids
        ],
        "approver_key": stage.approver_key or "",
        "approver_label": keys.get(stage.approver_key or "", None),
        "requirement_key": stage.requirement_key or "",
        "requirement_label": requirements.get(stage.requirement_key or "", None),
        "roles": [
            {
                "position_id": position_id,
                "title": roles.get(position_id, {}).get("title", ""),
                "department_name": roles.get(position_id, {}).get("department_name"),
                "is_active": roles.get(position_id, {}).get("is_active", False),
            }
            for position_id in position_ids
        ],
    }


def _user_map(user_ids) -> dict[int, dict]:
    """``{user_id: brief}`` одним запросом в users — как ``_role_map`` для
    должностей; имя пустое, если пользователя нет или users выключен
    (карточка маршрута — оформление, а не решение)."""
    ids = list(dict.fromkeys(int(x) for x in user_ids))
    if not ids:
        return {}
    try:
        return {row["id"]: row for row in users.get_users_brief(ids)}
    except Exception:
        return {}


def _role_map(position_ids) -> dict[int, dict]:
    """``{position_id: brief}`` одним запросом в HR.

    Имена разворачиваются пачкой на весь маршрут, а не по согласующему:
    маршрут из пяти этапов иначе дал бы пять походов в apps.users.
    """
    ids = list(dict.fromkeys(position_ids))
    if not ids:
        return {}
    return {row["id"]: row for row in hr.get_positions_brief(ids)}
