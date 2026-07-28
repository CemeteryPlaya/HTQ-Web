"""Реестр согласуемых типов — то, чем signoff заменяет межаппный импорт.

Движок обязан уметь две вещи с чужим объектом: сообщить ему результат
(«согласовано» / «отклонено») и показать его человеку в списке «ждёт моего
решения». Ни того, ни другого он не может сделать сам — ``apps.signoff``
не имеет права импортировать ``apps.contracts.models``
(``apps/core/tests/test_app_isolation.py``).

Поэтому зависимость перевёрнута: предметная аппка сама приходит и
регистрирует свой тип, отдавая колбэки. Направление импорта — contracts →
signoff.interface, разрешённое; обратного импорта не существует.

Регистрация — из ``AppConfig.ready()`` предметной аппки:

    class ContractsConfig(AppConfig):
        def ready(self):
            from . import approval_hooks
            approval_hooks.register()

Почему ``ready()``, а не автопоиск модулей по ``importlib``: автопоиск —
это тот же межаппный импорт, только спрятанный от проверки границ
(``test_app_isolation`` честно признаёт ``importlib`` своей слепой зоной).
Явный вызов из ``ready()`` видно и человеку, и грепу.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, Protocol

logger = logging.getLogger(__name__)


class UnknownSubject(Exception):
    """Запрошен тип объекта, который никто не регистрировал."""


class Describe(Protocol):
    def __call__(self, subject_id: int) -> dict | None:
        """``{"title": str, "url": str}`` или ``None``, если объекта нет."""


@dataclass(frozen=True)
class Subject:
    """Что предметная аппка рассказала signoff о своём типе объектов.

    ``model`` — класс модели, ПЕРЕДАННЫЙ предметной аппкой, а не
    импортированный отсюда. Разница принципиальная: правило границ
    запрещает signoff писать ``from apps.contracts.models import Budget``,
    но не запрещает contracts самой отдать ссылку на свой класс. Так signoff
    получает возможность вести СВОЁ поле (``Approvable.approval_state``) на
    чужой таблице, не зная ни имени аппки, ни устройства её моделей.

    Именно поэтому ``model`` обязан быть наследником ``Approvable``: signoff
    трогает у него ровно одну колонку — ту, которую сам же и объявил.

    ``on_approved``/``on_rejected`` — про ДОМЕННЫЕ последствия, а не про
    ``approval_state``: у договора, например, своя машина статусов с
    таблицей переходов, и согласовать её с результатом согласования вправе
    только сама аппка. Вызываются ВНУТРИ транзакции движка
    (см. ``engine._finish``), чтобы состояние процесса и состояние объекта
    коммитились вместе.

    ``describe`` — единственный способ показать чужой объект в интерфейсе
    signoff, не зная его модели.
    """

    subject_type: str
    label: str
    model: type
    on_approved: Callable[[int], None] | None = None
    on_rejected: Callable[[int], None] | None = None
    on_started: Callable[[int], None] | None = None
    on_cancelled: Callable[[int], None] | None = None
    describe: Describe | None = None


_SUBJECTS: dict[str, Subject] = {}


def register_subject(subject_type: str, *, label: str, model: type,
                     on_approved: Callable[[int], None] | None = None,
                     on_rejected: Callable[[int], None] | None = None,
                     on_started: Callable[[int], None] | None = None,
                     on_cancelled: Callable[[int], None] | None = None,
                     describe: Describe | None = None) -> Subject:
    """Объявить тип объектов согласуемым.

    Повторная регистрация того же типа ПЕРЕЗАПИСЫВАЕТ запись, а не падает:
    ``AppConfig.ready()`` при некоторых способах запуска (autoreload
    runserver, повторный ``django.setup()`` в тестах) выполняется больше
    одного раза, и падение на этом означало бы, что аппка не поднимается по
    причине, не имеющей отношения к делу.
    """
    from apps.signoff.models import Approvable

    if not subject_type or "." not in subject_type:
        raise ValueError(
            f"subject_type должен быть вида '<аппка>.<модель>', получено: "
            f"{subject_type!r}"
        )
    if not (isinstance(model, type) and issubclass(model, Approvable)):
        raise TypeError(
            f"model для «{subject_type}» должен наследовать "
            f"signoff.interface.Approvable, получено: {model!r}"
        )
    declared = getattr(model, "SIGNOFF_SUBJECT_TYPE", "")
    if declared != subject_type:
        # Рассинхрон молча приводит к тому, что submit_for_approval() на
        # модели уходит в один тип, а маршрут настроен на другой.
        raise ValueError(
            f"{model.__name__}.SIGNOFF_SUBJECT_TYPE = {declared!r}, "
            f"а регистрируется как {subject_type!r}"
        )

    subject = Subject(
        subject_type=subject_type, label=label, model=model,
        on_approved=on_approved, on_rejected=on_rejected,
        on_started=on_started, on_cancelled=on_cancelled, describe=describe,
    )
    if subject_type in _SUBJECTS:
        logger.debug("signoff: тип %s зарегистрирован повторно", subject_type)
    _SUBJECTS[subject_type] = subject
    return subject


def get_subject(subject_type: str) -> Subject:
    subject = _SUBJECTS.get(subject_type)
    if subject is None:
        known = ", ".join(sorted(_SUBJECTS)) or "(ни одного)"
        raise UnknownSubject(
            f"Тип «{subject_type}» не зарегистрирован в signoff. "
            f"Известные типы: {known}"
        )
    return subject


def registered_subjects() -> list[Subject]:
    return [_SUBJECTS[key] for key in sorted(_SUBJECTS)]


def is_registered(subject_type: str) -> bool:
    return subject_type in _SUBJECTS
