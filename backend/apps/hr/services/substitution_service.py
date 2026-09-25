"""Правила матрицы замещения ключевых должностей (HR-FRM-006), блок E.

Модель хранит строки, сервис хранит единственное правило, которое БД
выразить не может без расширения: у должности не бывает двух одновременно
действующих замещающих одного вида. Без него маршрут согласования получает
двух «основных» и выбирает первого попавшегося — то есть решение принимает
порядок строк в таблице.

Границы периодов ВКЛЮЧИТЕЛЬНЫЕ с обеих сторон: правило, действующее «по 31
мая», и правило «с 31 мая» в этот день пересекаются. Открытый конец
(``valid_to=None``) означает «пока не отменено приказом» и пересекается со
всем, что начинается позже.

Приём тот же, что у ``position_service`` с диапазонами весов уровней:
проверка пересечения живёт в сервисе, а БД держит то, что ей по силам —
точное совпадение (должность, вид, дата начала).
"""

from __future__ import annotations

import datetime as dt

from django.db.models import Q

from htqweb import date_rules

from apps.hr.models import Position, Substitution, SubstitutionKind


class SubstitutionError(Exception):
    """База ошибок домена. ``status``/``detail`` читает слой HTTP."""

    status = 400
    detail = "Ошибка матрицы замещения."


class SubstitutionSelfReferential(SubstitutionError):
    status = 422
    detail = "Должность не может замещать сама себя."


class SubstitutionPositionNotFound(SubstitutionError):
    status = 404
    detail = "Должность не найдена."


class SubstitutionOverlap(SubstitutionError):
    status = 409

    def __init__(self, existing: Substitution) -> None:
        self.existing = existing
        end = existing.valid_to.isoformat() if existing.valid_to else "бессрочно"
        self.detail = (
            f"У этой должности уже есть замещающий того же вида в пересекающийся "
            f"период ({existing.valid_from.isoformat()} — {end}). Закройте прежнее "
            f"замещение датой окончания, прежде чем заводить новое."
        )
        super().__init__(self.detail)


class SubstitutionNotFound(SubstitutionError):
    status = 404
    detail = "Замещение не найдено."


# primary раньше reserve — порядок документа, а не алфавита.
_KIND_ORDER = {SubstitutionKind.PRIMARY.value: 0, SubstitutionKind.RESERVE.value: 1}


def serialize(row: Substitution) -> dict:
    """SubstitutionOut. ``substitute_position_title`` кладётся рядом с id
    намеренно: карточка должности показывает название, и без него фронт
    делал бы второй запрос за списком должностей ради одной строки."""
    return {
        "id": row.id,
        "position_id": row.position_id,
        "substitute_position_id": row.substitute_position_id,
        "substitute_position_title": row.substitute_position.title,
        "kind": row.kind,
        "basis": row.basis,
        "note": row.note,
        "valid_from": row.valid_from.isoformat(),
        "valid_to": row.valid_to.isoformat() if row.valid_to else None,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


def _ordered(rows: list[Substitution]) -> list[Substitution]:
    return sorted(rows, key=lambda r: (_KIND_ORDER.get(r.kind, 9), -r.valid_from.toordinal()))


def list_for_position(position_id: int) -> list[Substitution]:
    """Все строки должности, включая истёкшие: карточка показывает историю."""
    rows = list(Substitution.objects
                .filter(position_id=position_id)
                .select_related("substitute_position"))
    return _ordered(rows)


def active_for_position(position_id: int, on_date: dt.date) -> list[Substitution]:
    """Действующие на дату строки с ДЕЙСТВУЮЩЕЙ замещающей должностью.

    Фильтр по ``is_active`` — здесь, а не у вызывающего: неактивная
    должность никого не прикроет, и вернуть её значит отправить маршрут
    согласования в тупик. Карточка должности при этом показывает правило как
    есть — это разные вопросы, и расхождение намеренное.
    """
    rows = list(Substitution.objects
                .filter(position_id=position_id, substitute_position__is_active=True)
                .filter(valid_from__lte=on_date)
                .filter(Q(valid_to__isnull=True) | Q(valid_to__gte=on_date))
                .select_related("substitute_position"))
    return _ordered(rows)


def _require_positions(*ids: int) -> None:
    known = set(Position.objects.filter(id__in=ids).values_list("id", flat=True))
    if set(ids) - known:
        raise SubstitutionPositionNotFound()


def _check_overlap(*, position_id: int, kind: str, valid_from: dt.date,
                   valid_to: dt.date | None, exclude_id: int | None = None) -> None:
    qs = Substitution.objects.filter(position_id=position_id, kind=kind)
    if exclude_id is not None:
        qs = qs.exclude(id=exclude_id)
    # Пересечение: начало нового не позже конца старого И конец нового не
    # раньше начала старого. Открытый конец — бесконечность справа.
    qs = qs.filter(Q(valid_to__isnull=True) | Q(valid_to__gte=valid_from))
    if valid_to is not None:
        qs = qs.filter(valid_from__lte=valid_to)
    clash = qs.order_by("valid_from").first()
    if clash is not None:
        raise SubstitutionOverlap(clash)


def create(*, position_id: int, substitute_position_id: int, kind: str,
           basis: str, note: str | None, valid_from: dt.date,
           valid_to: dt.date | None) -> Substitution:
    if position_id == substitute_position_id:
        raise SubstitutionSelfReferential()
    _require_positions(position_id, substitute_position_id)
    _check_overlap(position_id=position_id, kind=kind,
                   valid_from=valid_from, valid_to=valid_to)
    row = Substitution(
        position_id=position_id, substitute_position_id=substitute_position_id,
        kind=kind, basis=basis, note=note,
        valid_from=valid_from, valid_to=valid_to,
    )
    # Схема (``SubstitutionCreate(OrderedDates)``) уже проверяет ту же пару,
    # если обе даты приехали в теле запроса — этот вызов её не дублирует
    # зря: он делает create() симметричным update(), где схема частичный
    # PATCH не видит и проверка целиком лежит здесь.
    date_rules.assert_instance_ordered(row)
    row.save()
    return row


def update(substitution_id: int, **fields) -> Substitution:
    """Правка строки. Пересечение перепроверяется по ИТОГОВЫМ значениям и с
    исключением самой строки — иначе правка даты окончания считала бы
    пересечением саму себя."""
    row = (Substitution.objects
           .filter(id=substitution_id)
           .select_related("substitute_position")
           .first())
    if row is None:
        raise SubstitutionNotFound()

    allowed = {"substitute_position_id", "kind", "basis", "note",
               "valid_from", "valid_to"}
    changes = {k: v for k, v in fields.items() if k in allowed}
    for key, value in changes.items():
        setattr(row, key, value)

    if row.position_id == row.substitute_position_id:
        raise SubstitutionSelfReferential()
    _require_positions(row.position_id, row.substitute_position_id)
    _check_overlap(position_id=row.position_id, kind=row.kind,
                   valid_from=row.valid_from, valid_to=row.valid_to,
                   exclude_id=row.id)
    # По СЛИТОЙ паре, а не по присланным полям: PATCH может прислать только
    # одну дату, вторая лежит в уже загруженной строке. Без этой проверки
    # нарушение доходит до ck_substitution_dates и возвращается как 500.
    date_rules.assert_instance_ordered(row)
    row.save(update_fields=[*changes, "updated_at"])
    row.refresh_from_db()
    return row


def delete(substitution_id: int) -> None:
    deleted, _ = Substitution.objects.filter(id=substitution_id).delete()
    if not deleted:
        raise SubstitutionNotFound()
