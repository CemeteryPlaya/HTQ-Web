"""Отдел задачи при создании и правке (канбан-доски, K1.5).

Спека этапа 1 §K1.4, мастер-план K-07: рядовой сотрудник ставит отдел только
из своего поддерева или оставляет пустым (иначе 403); глава отдела при
создании — любой действующий отдел (тогда его отдел — отправитель, связь
``origin``), а правкой переводит задачу только внутри управляемых поддеревьев
(иначе 422: перенос в чужой отдел — отдельное действие, снимающее
исполнителей, S1-13, S1-19). Администратор — без ограничений, как раньше
(S1-12).

Порядок проверок (S1-05): сначала существование и активность отделов через
``hr.interface`` — выключенный ``hr`` даёт 503 раньше любого 403, ведь
проверить право без него нельзя; затем право.
"""

from __future__ import annotations

from apps.hr import interface as hr
from htqweb.errors import DomainError


def _clean(ids) -> list[int]:
    return [d for d in dict.fromkeys(ids) if d is not None]


def _require_active(ids: list[int]) -> None:
    briefs = {row["id"]: row for row in hr.get_departments_brief(ids)}
    for department_id in ids:
        row = briefs.get(department_id)
        if row is None or not row.get("is_active"):
            raise DomainError("task_department_inactive",
                              "Отдел не найден или закрыт", status=422)


def _forbidden() -> DomainError:
    return DomainError("task_department_forbidden",
                       "Задачу можно поставить только в свой отдел или его подотделы",
                       status=403)


def _use_transfer() -> DomainError:
    return DomainError("task_department_use_transfer",
                       "Чтобы отдать задачу в другой отдел, используйте «Отправить в отдел»",
                       status=422)


def origin_for_create(scope, department_ids) -> int | None:
    """Проверить отделы новой задачи; вернуть отдел-отправитель или ``None``.

    Отправитель есть, только когда глава ставит задачу в отдел вне своих
    поддеревьев: первый из управляемых отделов, в поддерево которого цель не
    входит (обычно — сам его отдел)."""
    ids = _clean(department_ids)
    if not ids or scope.elevated:
        return None
    _require_active(ids)
    if set(ids) <= scope.department_ids:
        return None
    if not scope.managed_ids:
        raise _forbidden()
    return min(scope.managed_ids)


def check_change(scope, task, department_ids) -> None:
    """Проверить отделы задачи после правки.

    ``department_ids`` — итоговый набор отделов-участников (основной первым),
    посчитанный ПОСЛЕ перекладки ``department_ids[0]`` в основной: иначе
    правка одним ``department_ids`` обошла бы проверку (S1-19). Задача из
    управляемого поддерева остаётся в управляемых поддеревьях, прочие — в
    своём поддереве вызывающего.
    """
    ids = _clean(department_ids)
    if not ids or scope.elevated:
        return
    _require_active(ids)
    zone = (scope.managed_subtree if task.department_id in scope.managed_subtree
            else scope.department_ids)
    if set(ids) <= zone:
        return
    raise _use_transfer() if scope.managed_ids else _forbidden()
