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

import inspect
import logging
from dataclasses import dataclass
from typing import Callable, Protocol

logger = logging.getLogger(__name__)


class UnknownSubject(Exception):
    """Запрошен тип объекта, который никто не регистрировал."""


class Describe(Protocol):
    def __call__(self, subject_id: int) -> dict | None:
        """``{"title": str, "url": str}`` или ``None``, если объекта нет."""


class Facts(Protocol):
    def __call__(self, subject_id: int) -> dict:
        """Плоский словарь скаляров, по которым выбираются ветки маршрута."""


class FactFields(Protocol):
    def __call__(self, scope: str = "") -> list[dict]:
        """Схема доступных фактов: ``{"key", "label", "type", "options"}``.

        ``scope`` необязателен и для типов без областей не передаётся:
        реестр смотрит на сигнатуру при регистрации (``_takes_scope``) и
        нульарные колбэки зовёт без аргументов.
        """


class ScopeOf(Protocol):
    def __call__(self, subject_id: int) -> str:
        """Область объекта (``ApprovalRoute.scope``); ``""`` — весь тип."""


class Scopes(Protocol):
    def __call__(self) -> list[dict]:
        """Какие области бывают: ``[{"scope", "label"}]`` — для списка маршрутов."""


class Approvers(Protocol):
    def __call__(self, subject_id: int, key: str) -> list[int]:
        """Кого объект называет согласующими по ключу из ``approver_fields``."""


class ApproverFields(Protocol):
    def __call__(self, scope: str = "") -> list[dict]:
        """Какие ключи можно спрашивать у объекта: ``[{"key", "label"}]``."""


class OnEvent(Protocol):
    def __call__(self, subject_id: int, kind: str, payload: dict) -> None:
        """Событие процесса — после коммита, best-effort (SSE, свои журналы)."""


class RequirementFields(Protocol):
    def __call__(self, scope: str = "") -> list[dict]:
        """Что этап может ТРЕБОВАТЬ от объекта: ``[{"key", "label"}]``.

        Не «кто согласует», а «что должно быть сделано на объекте», прежде
        чем этап закроется: заполнено поле, приложен скан. Редактор
        маршрута предлагает эти ключи в поле «этап требует от объекта».
        """


class CheckRequirement(Protocol):
    def __call__(self, subject_id: int, key: str) -> str | None:
        """Выполнено ли требование ``key`` на объекте.

        ``None`` — выполнено; строка — ПОЧЕМУ нет, по-русски и для человека:
        она уходит согласующему в отказ 409 как есть («поле «Поставщик» не
        заполнено»). Не булево намеренно: «нельзя» без «что сделать» — это
        отказ, с которым человек остаётся один на один.
        """


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

    ``on_approved``/``on_rejected``/``on_rework`` — про ДОМЕННЫЕ
    последствия, а не про ``approval_state``: у договора, например, своя
    машина статусов с таблицей переходов, и согласовать её с результатом
    согласования вправе только сама аппка. Вызываются ВНУТРИ транзакции
    движка (см. ``engine._finish``), чтобы состояние процесса и состояние
    объекта коммитились вместе.

    ``on_rework`` вызывается ДВАЖДЫ по разным поводам — когда согласующий
    вернул объект решением и когда уже закрытый круг открыли заново
    (``engine.reopen``). Для предметной аппки это одно и то же событие
    («объект снова правится»), поэтому колбэк один; отличать поводы ей
    незачем, а движку — есть где (журнал).

    ``describe`` — единственный способ показать чужой объект в интерфейсе
    signoff, не зная его модели.

    ``facts``/``fact_fields`` — то же самое для УСЛОВНЫХ ВЕТОК: движок не
    может спросить у бюджета страну его администратора, поэтому аппка сама
    снимает с объекта плоский словарь скаляров (``facts``) и отдельно
    объявляет, что из него разрешено спрашивать в условии и как показать это
    в редакторе маршрута (``fact_fields``). Обе необязательны: тип без них
    просто не поддерживает ветвление, и редактор не покажет ему условий.
    Подробнее — ``services/conditions.py``.

    ``fact_fields`` — функция, а не константа, потому что варианты выбора
    берутся из справочника в БД: список стран меняется без перезапуска, и
    зафиксировать его на импорте модуля значило бы показывать в редакторе
    вчерашний справочник.

    ``scope_of``/``scopes`` — ОБЛАСТИ внутри типа (``ApprovalRoute.scope``):
    тип с несколькими маршрутами (у конструктора форм — по маршруту на
    шаблон) сам говорит, к какой области относится объект и какие области
    вообще есть. Тип без них живёт одним маршрутом на весь тип.

    ``approvers``/``approver_fields`` — согласующие, которых называет сам
    объект (``ApproverKind.SUBJECT``): та же пара «данные + схема», что
    ``facts``/``fact_fields``, и с тем же правилом — схема без данных
    запрещена.

    ``on_event`` — уведомление о событиях процесса ПОСЛЕ коммита: для SSE,
    собственных лент и прочего оформления. Ошибки в нём глушатся, как у
    ``describe``: оформление не роняет согласование.

    ``takes_scope_*`` — вычисляются при регистрации по сигнатуре колбэка:
    существующие нульарные ``fact_fields`` (contracts) продолжают работать,
    а типу с областями схема нужна ПО области.
    """

    subject_type: str
    label: str
    model: type
    on_approved: Callable[[int], None] | None = None
    on_rejected: Callable[[int], None] | None = None
    on_rework: Callable[[int], None] | None = None
    on_started: Callable[[int], None] | None = None
    on_cancelled: Callable[[int], None] | None = None
    describe: Describe | None = None
    facts: Facts | None = None
    fact_fields: FactFields | None = None
    scope_of: ScopeOf | None = None
    scopes: Scopes | None = None
    approvers: Approvers | None = None
    approver_fields: ApproverFields | None = None
    on_event: OnEvent | None = None
    requirement_fields: RequirementFields | None = None
    check_requirement: CheckRequirement | None = None
    takes_scope_fact_fields: bool = False
    takes_scope_approver_fields: bool = False
    takes_scope_requirement_fields: bool = False


_SUBJECTS: dict[str, Subject] = {}


def register_subject(subject_type: str, *, label: str, model: type,
                     on_approved: Callable[[int], None] | None = None,
                     on_rejected: Callable[[int], None] | None = None,
                     on_rework: Callable[[int], None] | None = None,
                     on_started: Callable[[int], None] | None = None,
                     on_cancelled: Callable[[int], None] | None = None,
                     describe: Describe | None = None,
                     facts: Facts | None = None,
                     fact_fields: FactFields | None = None,
                     scope_of: ScopeOf | None = None,
                     scopes: Scopes | None = None,
                     approvers: Approvers | None = None,
                     approver_fields: ApproverFields | None = None,
                     on_event: OnEvent | None = None,
                     requirement_fields: RequirementFields | None = None,
                     check_requirement: CheckRequirement | None = None) -> Subject:
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

    if fact_fields is not None and facts is None:
        # Иначе редактор маршрута предложит поля, которых на запуске не
        # окажется, и каждое такое условие упадёт ConditionError'ом уже в
        # руках пользователя. Обратное сочетание законно: ``facts`` без
        # ``fact_fields`` — это снимок для журнала без права ветвиться по нему.
        raise ValueError(
            f"«{subject_type}»: fact_fields объявлены без facts — условия "
            f"будет не на чем проверять"
        )
    if approver_fields is not None and approvers is None:
        # То же правило, что у fact_fields/facts: редактор предложил бы
        # ключи, по которым на запуске некого спросить.
        raise ValueError(
            f"«{subject_type}»: approver_fields объявлены без approvers — "
            f"согласующих будет не у кого спросить"
        )
    if scopes is not None and scope_of is None:
        raise ValueError(
            f"«{subject_type}»: scopes объявлены без scope_of — маршрут по "
            f"области не найдёт своих объектов"
        )
    if requirement_fields is not None and check_requirement is None:
        # Та же пара, что approver_fields/approvers: ключи, которые редактор
        # предложит, а проверить на решении будет некому.
        raise ValueError(
            f"«{subject_type}»: requirement_fields объявлены без "
            f"check_requirement — требование будет некому проверить"
        )
    # Сами ``fact_fields()`` здесь НЕ вызываются: регистрация идёт из
    # AppConfig.ready(), где обращаться в БД нельзя (см. докстринг
    # interface.py), а варианты выбора приходят как раз из справочника.
    # Их проверяет conditions.validate_fields() в момент чтения.

    subject = Subject(
        subject_type=subject_type, label=label, model=model,
        on_approved=on_approved, on_rejected=on_rejected, on_rework=on_rework,
        on_started=on_started, on_cancelled=on_cancelled, describe=describe,
        facts=facts, fact_fields=fact_fields,
        scope_of=scope_of, scopes=scopes,
        approvers=approvers, approver_fields=approver_fields,
        on_event=on_event,
        requirement_fields=requirement_fields, check_requirement=check_requirement,
        takes_scope_fact_fields=_takes_scope(fact_fields),
        takes_scope_approver_fields=_takes_scope(approver_fields),
        takes_scope_requirement_fields=_takes_scope(requirement_fields),
    )
    if subject_type in _SUBJECTS:
        logger.debug("signoff: тип %s зарегистрирован повторно", subject_type)
    _SUBJECTS[subject_type] = subject
    return subject


def _takes_scope(fn) -> bool:
    """Принимает ли колбэк схемы аргумент области.

    По сигнатуре, а не по try/except на вызове: ``TypeError`` изнутри чужой
    функции неотличим от ``TypeError`` из-за лишнего аргумента.
    """
    if fn is None:
        return False
    try:
        return len(inspect.signature(fn).parameters) >= 1
    except (TypeError, ValueError):
        return False


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


def fields_for(subject_type: str, scope: str = "") -> list[dict]:
    """Схема фактов типа — для редактора маршрута и проверки условий.

    Пустой список у типа, который ветвление не поддерживает: это не ошибка,
    а «условия здесь настраивать нельзя», и редактор просто не покажет их.
    ``scope`` уходит только колбэку, который его принимает (см. ``Subject``).
    """
    from apps.signoff.services import conditions

    subject = get_subject(subject_type)
    if subject.fact_fields is None:
        return []
    raw = (subject.fact_fields(scope) if subject.takes_scope_fact_fields
           else subject.fact_fields())
    return conditions.validate_fields(raw)


def approver_fields_for(subject_type: str, scope: str = "") -> list[dict]:
    """Какие ключи ``ApproverKind.SUBJECT`` допустимы у этапа этого типа.

    Пустой список — тип не умеет называть согласующих сам; редактор не
    покажет такой вид этапа.
    """
    subject = get_subject(subject_type)
    if subject.approver_fields is None:
        return []
    raw = (subject.approver_fields(scope) if subject.takes_scope_approver_fields
           else subject.approver_fields())
    out: list[dict] = []
    seen: set[str] = set()
    for row in raw:
        key = str(row.get("key", "")).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append({"key": key, "label": str(row.get("label") or key)})
    return out


def requirement_fields_for(subject_type: str, scope: str = "") -> list[dict]:
    """Что этап может требовать от объекта этого типа (и области).

    Пустой список — тип ничего такого не умеет; редактор не покажет поле.
    """
    subject = get_subject(subject_type)
    if subject.requirement_fields is None:
        return []
    raw = (subject.requirement_fields(scope) if subject.takes_scope_requirement_fields
           else subject.requirement_fields())
    out: list[dict] = []
    seen: set[str] = set()
    for row in raw:
        key = str(row.get("key", "")).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append({"key": key, "label": str(row.get("label") or key)})
    return out


def check_requirement_for(subject_type: str, subject_id: int, key: str) -> str | None:
    """Выполнено ли требование этапа на объекте; строка — почему нет.

    Ошибку НЕ глушим — как у ``facts_for`` и ``approvers_for``: здесь
    решается, можно ли закрыть этап, и сломанный колбэк должен быть виден,
    а не молча пропускать шаг.
    """
    subject = get_subject(subject_type)
    if subject.check_requirement is None:
        return None
    reason = subject.check_requirement(subject_id, key)
    return str(reason) if reason else None


def scope_for(subject_type: str, subject_id: int) -> str:
    """Область объекта; ``""`` у типов без областей."""
    subject = get_subject(subject_type)
    if subject.scope_of is None:
        return ""
    return str(subject.scope_of(subject_id) or "")


def scopes_for(subject_type: str) -> list[dict]:
    """``[{"scope", "label"}]`` — какие маршруты у типа могут быть."""
    subject = get_subject(subject_type)
    if subject.scopes is None:
        return []
    return [{"scope": str(row["scope"]), "label": str(row.get("label") or row["scope"])}
            for row in subject.scopes() if row.get("scope")]


def scope_label(subject_type: str, scope: str) -> str | None:
    """Подпись области — из ``scopes()``; ``None``, если тип её не назвал.

    Ошибки колбэка глушатся: подпись — оформление, и список маршрутов не
    должен падать из-за сломанного справочника одной аппки.
    """
    if not scope:
        return None
    try:
        for row in scopes_for(subject_type):
            if row["scope"] == scope:
                return row["label"]
    except Exception:
        logger.warning("signoff: scopes() для %s упал", subject_type, exc_info=True)
    return None


def approvers_for(subject_type: str, subject_id: int, key: str) -> list[int]:
    """Кого объект называет согласующими по ключу. Ошибку НЕ глушим — как
    у ``facts_for``: здесь решается, кто согласует."""
    subject = get_subject(subject_type)
    if subject.approvers is None:
        return []
    raw = subject.approvers(subject_id, key) or []
    return [int(user_id) for user_id in dict.fromkeys(raw) if user_id is not None]


def facts_for(subject_type: str, subject_id: int) -> dict:
    """Факты объекта — то, по чему выбираются ветки и что ложится в журнал.

    Ошибку ``facts()`` НЕ глушим, в отличие от ``describe()``: заголовок
    карточки — оформление, а факты решают, кто будет согласовывать. Молча
    подставить пустой словарь значило бы отправить объект не по той ветке.
    """
    from apps.signoff.services import conditions

    subject = get_subject(subject_type)
    if subject.facts is None:
        return {}
    return conditions.normalize_facts(subject.facts(subject_id))


def is_registered(subject_type: str) -> bool:
    return subject_type in _SUBJECTS
