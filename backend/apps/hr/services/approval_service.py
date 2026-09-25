"""Отправка кадрового предмета на согласование — блок G.

Одна функция на все десять предметов, а не десять почти одинаковых: вся
разница между ними — какой класс достать по типу, и она выражается
таблицей, а не копией кода. Предметных проверок «можно ли отправлять» здесь
нет намеренно: у кадровых заявок нет собственного жизненного цикла вроде
«закрытый бюджет» — заявка либо существует, либо нет. Всё остальное
(повторная отправка, отсутствие маршрута, непригодный маршрут) отбивает сам
движок и отдаёт своими исключениями.
"""

from apps.signoff import interface as signoff


class SubjectNotFound(Exception):
    """404: такого предмета этого типа в текущей компании нет."""

    status = 404
    detail = "Объект не найден."


def _model_for(subject_type: str):
    """Класс предмета по его типу — или ``None`` для незнакомого типа.

    Таблица строится из реестра signoff, а не дублируется здесь: реестр уже
    знает соответствие, и вторая копия разъехалась бы с ним при добавлении
    предмета.
    """
    from apps.hr import approval_hooks

    return approval_hooks.SUBJECT_MODELS.get(subject_type)


def submit_for_approval(subject_type: str, subject_id: int, *,
                        actor_id: int | None = None) -> dict:
    """Запустить согласование предмета. Возвращает карточку процесса.

    Карточка процесса, а не предметный объект: после отправки человеку надо
    показать «на каком этапе и кто согласует», и это знает signoff.
    """
    model = _model_for(subject_type)
    if model is None:
        raise SubjectNotFound()
    if not model.objects.filter(pk=subject_id).exists():
        raise SubjectNotFound()
    # signoff.start_process принимает инициатора как ``initiator_id``, а не
    # ``actor_id`` (см. apps/signoff/interface.py) — та же несовпадающая пара
    # имён, что и в apps/contracts/services/budget_service.py::submit_for_approval.
    return signoff.start_process(subject_type=subject_type, subject_id=subject_id,
                                 initiator_id=actor_id, enrich=True)
