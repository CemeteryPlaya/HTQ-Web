"""Движок согласования: запуск процесса, приём решений, продвижение по этапам.

Вся логика домена живёт здесь; вьюхи только разбирают запрос и зовут эти
функции.

Три правила, из которых следует всё остальное:

1. **Отрицательное решение закрывает круг сразу.** И отказ, и возврат на
   доработку на любом этапе завершают весь процесс немедленно — остальные
   этапы не получают запросов, уже выданные гасятся как «не потребовалось».
   Это требование заказчика и одновременно безопасное поведение: закрытый
   процесс — состояние, из которого ничего плохого не произойдёт, в отличие
   от молча продолжающегося согласования. Разница между двумя решениями не
   в механике, а в судьбе ОБЪЕКТА: возврат на доработку отпирает его для
   правки, отказ — нет (``models.ApprovalState``).
2. **Группа этапов проходится целиком.** Этапы с одинаковым ``order`` идут
   параллельно; следующая группа активируется, только когда ВСЕ этапы
   текущей согласованы.
3. **Колбэк предметной аппки — внутри транзакции, уведомление — после
   коммита.** Состояние процесса и состояние предметного объекта обязаны
   стать согласованными атомарно (иначе «процесс согласован, бюджет нет»);
   уведомление же — внешний эффект, и рассылать его по откатившейся
   транзакции нельзя.
4. **Ветвление разбирается один раз, на запуске.** Условные этапы отсеиваются
   в ``start`` до снимка (``services/conditions.py``), поэтому всё остальное в
   этом модуле работает с обычным линейным списком групп и про условия не
   знает. Пересчёта веток по ходу согласования нет: сменившийся у бюджета
   администратор не переигрывает уже идущий процесс — ровно так же, как его
   не переигрывает правка маршрута.

Гонки. Все переходы берут ``SELECT … FOR UPDATE`` на строку процесса. Без
этого два согласующих, закрывающих последний этап одновременно, оба увидят
«все остальные согласовали» и оба вызовут ``on_approved`` — предметная
аппка получит команду дважды.
"""

from __future__ import annotations

import logging
from datetime import timezone as _tz
from datetime import datetime

from django.db import IntegrityError, transaction
from django.http import Http404

from apps.core.services import ServiceDisabled
from apps.signoff.models import (
    ApprovalEvent,
    ApprovalProcess,
    ApprovalProcessStage,
    ApprovalRoute,
    ApprovalState,
    ApprovalTask,
    ApproverKind,
    ProcessState,
    Quorum,
    StageState,
    TaskState,
)
from apps.signoff.services import conditions, registry, resolution
# Соседи — только через interface (apps/core/tests/test_app_isolation.py).
from apps.hr import interface as hr
from apps.messenger import interface as messenger
from apps.users import interface as users

logger = logging.getLogger(__name__)

APPROVE = "approve"
REJECT = "reject"
# «Вернуть на доработку» — решение, а не отдельный механизм: его принимает
# тот же согласующий, тем же запросом и на том же этапе, что и два других.
# От отказа отличается последствием для ОБЪЕКТА: только оно отпирает его для
# правки (``Approvable.assert_editable``). Отказ — «документ не годится»,
# возврат — «поправьте и пришлите снова».
REWORK = "rework"
DECISIONS = (APPROVE, REJECT, REWORK)

# Вид события журнала под каждое решение. Таблицей, а не склейкой строки
# из самого решения: "reject" + "d" даёт "task_rejectd".
_EVENT_KIND = {APPROVE: "task_approved", REJECT: "task_rejected",
               REWORK: "task_rework"}

# Чем заканчивается процесс и в каком состоянии остаётся закрывший его этап.
# Отказ и возврат на доработку идут одним кодом (``_close_by_decision``) —
# различаются они только этой парой состояний и последствиями в ``_finish``.
_DECISION_OUTCOME = {
    REJECT: (TaskState.REJECTED, StageState.REJECTED, ProcessState.REJECTED),
    REWORK: (TaskState.REWORK, StageState.REWORK, ProcessState.REWORK),
}


class SignoffError(Exception):
    """Базовая ошибка домена — вьюха переводит её в 409."""


class RouteNotConfigured(SignoffError):
    """Для типа объекта нет активного маршрута."""


class AlreadyInApproval(SignoffError):
    """У объекта уже идёт согласование."""


class NotAnApprover(SignoffError):
    """Пользователь пытается решить не свой запрос."""


class ProcessClosed(SignoffError):
    """Процесс уже завершён — решения больше не принимаются."""


class ProcessStillRunning(SignoffError):
    """``reopen`` на процессе, который ещё идёт.

    Отдельно от ``ProcessClosed`` — это ровно обратная ошибка, и путать их
    в тексте нельзя: пока круг идёт, вернуть объект на доработку может
    согласующий своим решением, а инициатор — отозвать заявку. Отпирать его
    задним числом в это время не нужно и некому.
    """


class RouteUnusable(SignoffError):
    """Маршрут нельзя исполнить на этом объекте.

    Причины, и все обнаруживаются только на запуске:

    * пустой этап;
    * ни одного АКТИВНОГО согласующего — согласующие заданы поимённо, а люди
      увольняются, и маршрут из одних деактивированных породил бы процесс,
      который физически некому двигать;
    * в группе условных этапов не сошлось ни одно условие и нет этапа
      «иначе» (``conditions.NoBranchMatched``);
    * этап подписывает инициатор (``ApproverKind.INITIATOR``), а инициатора
      у процесса нет — так бывает при операторском запуске без
      ``initiator_id``.

    Во всех случаях лучше отказать на запуске с внятным текстом, чем создать
    заявку, навсегда зависшую на первом этапе или, того хуже, тихо прошедшую
    мимо целой группы согласующих.
    """


class SubjectLocked(SignoffError):
    """Объект заперт согласованием — правка, удаление и повторная отправка.

    Поднимают двое: ``Approvable.assert_editable``
    (``apps/signoff/models.py``), которого предметные аппки зовут первой
    строкой своих операций правки, и ``start`` — на попытке отправить
    заново то, по чему решение уже принято.

    Почему запрет вообще существует: ветвление маршрута разбирается ОДИН
    раз, на запуске, из снимка ``ApprovalProcess.subject_facts``, и
    согласующие принимают решение по тому, что видели тогда. Правка
    посреди процесса означает, что подписи собраны под одним документом, а
    в карточке лежит другой — причём этап, который сумму в 50 млн ₸ не
    пропустил бы, уже пройден по сумме в 5 млн. После решения справедливо то
    же самое, только задним числом: документ, который согласовали, обязан
    остаться тем, который согласовали.

    Ключ от замка ровно один — возврат на доработку (решение ``REWORK`` или
    ``reopen`` для уже закрытого круга). Он и переводит объект в
    ``ApprovalState.REWORK`` — единственное, кроме черновика, состояние, в
    котором объект правится.

    Наследуется от ``SignoffError`` не для красоты: предметные вьюхи уже
    ловят его как конфликт состояния и переводят в 409 с текстом
    (``apps/contracts/views.py``, кортеж ``CONFLICTS``).
    """


class AttachmentRequired(SignoffError):
    """Этап требует приложенный документ, а его нет.

    Проверяется на СОГЛАСОВАНИИ и только на нём: требовать PDF от того, кто
    отклоняет, незачем — отказ объясняется комментарием, а документа, который
    отказавшему полагалось бы подписать, не существует.
    """


class SubjectRequirementUnmet(SignoffError):
    """Этап требует от объекта результата, которого на нём ещё нет.

    Третий гейт рядом с документом и пояснением, но о другом: те два — про
    решение (что принёс согласующий), этот — про ОБЪЕКТ (что на нём должно
    быть сделано: заполнен поставщик, приложен скан). Выполнено ли, знает
    предметная аппка — движок лишь спрашивает её по ключу этапа и отдаёт её
    объяснение человеку как есть. Тоже только на согласовании: отказать и
    вернуть на доработку можно и с незаполненным объектом — ровно так и
    возвращают.
    """


class CommentRequired(SignoffError):
    """Этап требует пояснение к решению, а комментарий пуст.

    Проверяется, как и ``AttachmentRequired``, только на СОГЛАСОВАНИИ: у
    отказа и возврата на доработку комментарий и так по смыслу обязателен
    (это и есть объяснение решения), а настойчивость формы здесь пришлась бы
    ровно на тот случай, где человек и без галочки пишет, зачем отклонил.
    Гейт нужен обратному — «согласовано» без единого слова, — поэтому стоит
    он на ``approve``.
    """


class InvalidDecision(SignoffError):
    """Решение составлено неверно — 422, а не 409: запрос не противоречит
    состоянию процесса, в нём не хватает или неверно поле (вариант голоса,
    длина комментария)."""


class CommentTooShort(InvalidDecision):
    """Отказ или возврат на доработку с комментарием короче, чем требует
    маршрут (``reject_comment_min``, BR-060)."""


class PreapprovalMismatch(SignoffError):
    """Предсогласованная должность не встречается ни на одном этапе
    маршрута объекта — предметная аппка ошиблась, и молча согласовать
    «что-то» вместо неё нельзя (D-26)."""


class SelfApprovalForbidden(SignoffError):
    """Автор документа решает по нему сам при запрете самосогласования
    (``forbid_self_approval``, BR-061) — 403. Задач автору такой маршрут не
    ставит; проверка на решении — вторая линия, на случай задачи, созданной
    до включения флага или вручную."""


class OptionError(InvalidDecision):
    """Голос за вариант не принят. 422, а не 409 (мастер-план БЗО, B1.3):
    запрос не противоречит состоянию процесса — в нём не хватает или
    неверно поле ``option_key``."""


class OptionRequired(OptionError):
    """У объекта есть варианты (исходный документ и его альтернативы), а
    «согласовать» не назвало, какой. Молча согласовать исходный значило бы
    отдать голос против предложения, которого человек, может быть, и не
    видел — поэтому выбор обязателен, в том числе у пакетного «одобрить
    всё»."""


class OptionRejected(OptionError):
    """Неизвестный ключ варианта или предметная аппка объяснила, почему за
    него голосовать нельзя (альтернатива дороже, а остатка статьи не
    хватает)."""


def _now() -> datetime:
    return datetime.now(_tz.utc)


# ═══════════════════════════════════════════════════════════════════════
# Запуск
# ═══════════════════════════════════════════════════════════════════════

@transaction.atomic
def start(*, subject_type: str, subject_id: int | str,
          initiator_id: int | None = None,
          scope: str | None = None,
          preapproved: list[dict] | None = None) -> ApprovalProcess:
    """Запустить согласование объекта по активному маршруту его типа.

    ``scope`` — область маршрута; по умолчанию её называет сама предметная
    аппка (``Subject.scope_of``), явный аргумент — для операторского запуска.

    ``preapproved`` — ``[{position_id, actor_id, label}]``: группы этих
    должностей считаются уже согласованными (новый договор по альтернативе,
    за которую голосовали при выборе, D-26). Задач им не ставится; этап, у
    которого предсогласованы все группы, закрывается сразу с событием
    ``stage_preapproved``.
    """
    subject = registry.get_subject(subject_type)  # UnknownSubject → 409/422
    # Каноническая строка ключа модели: 5, "5" и "05" — один объект, и
    # частичный уникальный индекс видит одно значение (registry.storage_key).
    subject_id = registry.storage_key(subject_type, subject_id)
    if scope is None:
        scope = registry.scope_for(subject_type, subject_id)

    route = (ApprovalRoute.objects
             .filter(subject_type=subject_type, scope=scope, is_active=True)
             .prefetch_related("stages__roles").first())
    if route is None:
        where = registry.scope_label(subject_type, scope) if scope else None
        raise RouteNotConfigured(
            f"Для «{subject.label}»{f' ({where})' if where else ''} не настроен "
            f"маршрут согласования"
        )

    stages = list(route.stages.all())
    if not stages:
        raise RouteUnusable(f"В маршруте «{route.name}» нет ни одного этапа")

    _assert_submittable(subject, subject_id)

    # Ветвление разбирается ЗДЕСЬ, до снимка: дальше движок видит обычный
    # линейный список групп и про условия не знает вовсе (см. докстринг
    # services/conditions.py). Поэтому act/_advance/кворум/блокировки
    # ветвления не касаются.
    facts = registry.facts_for(subject_type, subject_id)
    selected = _select_stages(stages, facts, subject=subject, route=route)
    pre = _preapproved_positions(preapproved, selected)
    # Флаги маршрута — снимком в процесс: правка маршрута идущий процесс не
    # меняет (ТЗ §16.1 п.2). Без флагов всё ниже — прежнее поведение.
    flags = resolution.route_flags_of(route)
    if flags["lazy_resolution"]:
        # Исполнители — при активации этапа, по снимку этапа (ТЗ §16.1 п.2);
        # на запуске проверяется только сама настройка.
        for item in selected:
            _check_stage_configured(item.stage, initiator_id=initiator_id)
        plan = [(item.stage.order, item.stage, item.matched_by, None)
                for item in selected]
    else:
        plan = _resolve_stages(selected, initiator_id=initiator_id,
                               subject_type=subject_type, subject_id=subject_id)

    try:
        process = ApprovalProcess.objects.create(
            subject_type=subject_type, subject_id=subject_id, scope=scope,
            route_id=route.pk, initiator_id=initiator_id,
            state=ProcessState.PENDING, subject_facts=facts, route_flags=flags,
            preapproved=list(pre.values()),
        )
    except IntegrityError as exc:
        # Частичный уникальный индекс uq_signoff_one_pending_process_per_subject.
        raise AlreadyInApproval(
            f"«{subject.label}» уже находится на согласовании"
        ) from exc

    first_order = min(order for order, _, _, _ in plan)
    for order, stage, matched_by, approvers_by_position in plan:
        process_stage = ApprovalProcessStage.objects.create(
            process=process, order=order, name=stage.name, quorum=stage.quorum,
            condition=stage.condition, matched_by=matched_by,
            approver_kind=stage.approver_kind,
            role_ids=([row.position_id for row in stage.roles.all()]
                      if stage.approver_kind == ApproverKind.POSITION else []),
            user_ids=(list(stage.user_ids or [])
                      if stage.approver_kind == ApproverKind.USERS else []),
            approver_key=(stage.approver_key
                          if stage.approver_kind == ApproverKind.SUBJECT else ""),
            requires_attachment=stage.requires_attachment,
            requires_comment=stage.requires_comment,
            votes_option=stage.votes_option,
            requirement_key=stage.requirement_key or "",
            state=StageState.WAITING,
        )
        _log_preapproved(process, process_stage, pre, actor_id=initiator_id)
        if approvers_by_position is not None:
            # Без ленивого разрешения исполнители известны уже сейчас.
            outcome = resolution.Resolution(groups={
                key: ids for key, ids in approvers_by_position.items() if key not in pre})
            if stage.approver_kind != ApproverKind.INITIATOR:
                resolution.apply_self_approval(outcome, initiator_id=initiator_id,
                                               flags=flags)
            _create_tasks(process, process_stage, outcome, flags=flags)

    # Отсеянные ветки — в журнал: карточка процесса показывает только то, что
    # в него вошло, и вопрос «а почему тут нет финконтроля по Узбекистану»
    # иначе остался бы без ответа.
    taken = {item.stage.pk for item in selected}
    _log(process, "started", actor_id=initiator_id, payload={
        "route_id": route.pk, "route_name": route.name,
        "facts": facts,
        "skipped_stages": [{"order": stage.order, "name": stage.name,
                            "condition": stage.condition}
                           for stage in stages if stage.pk not in taken],
    })

    # Первая группа становится активной ДО колбэка предметной аппки — как и
    # прежде: он вправе спросить, на каком этапе объект.
    _open_group(process, first_order, actor_id=initiator_id)

    if subject.on_started is not None:
        subject.on_started(registry.native_id(subject_type, subject_id))
    _set_subject_state(subject_type, subject_id, ApprovalState.PENDING)

    # Первая группа могла закрыться сразу (все её группы пропущены при
    # самосогласовании) — тогда дальше; иначе просто уведомить исполнителей.
    if not _advance(process, actor_id=initiator_id):
        _notify_active_stages(process)
    return process


def _preapproved_positions(preapproved, selected) -> dict[int, dict]:
    """``{position_id: {position_id, actor_id, label}}`` — только должности,
    которые реально стоят на отобранных этапах маршрута."""
    if not preapproved:
        return {}
    on_route = {row.position_id for item in selected
                if item.stage.approver_kind == ApproverKind.POSITION
                for row in item.stage.roles.all()}
    out: dict[int, dict] = {}
    for item in preapproved:
        position_id = int(item["position_id"])
        if position_id not in on_route:
            raise PreapprovalMismatch(
                f"Должности #{position_id} нет ни на одном этапе маршрута — "
                f"предсогласовать её нельзя")
        out[position_id] = {"position_id": position_id,
                            "actor_id": item.get("actor_id"),
                            "label": item.get("label") or "Согласовано заранее"}
    return out


def _log_preapproved(process: ApprovalProcess, stage: ApprovalProcessStage,
                     pre: dict[int, dict], *, actor_id: int | None) -> None:
    hits = [pre[position_id] for position_id in (stage.role_ids or []) if position_id in pre]
    if hits:
        _log(process, "stage_preapproved", actor_id=actor_id, payload={
            "stage": stage.name, "order": stage.order,
            "position_ids": [row["position_id"] for row in hits],
            "actor_ids": [row["actor_id"] for row in hits],
            "label": hits[0]["label"]})


def _check_stage_configured(stage, *, initiator_id: int | None) -> None:
    """Ленивый маршрут: этап, у которого исполнителей не бывает в принципе,
    — отказ на запуске, а не «Нет исполнителя» посреди процесса. «Нет
    исполнителя» — про людей, а не про пустую настройку."""
    if stage.approver_kind == ApproverKind.INITIATOR and initiator_id is None:
        raise RouteUnusable(
            f"Этап «{stage.name}» подписывает инициатор, но согласование "
            f"запущено без инициатора")
    if stage.approver_kind == ApproverKind.USERS and not stage.user_ids:
        raise RouteUnusable(f"На этапе «{stage.name}» не назван ни один согласующий")
    if (stage.approver_kind == ApproverKind.POSITION
            and not any(True for _ in stage.roles.all())):
        raise RouteUnusable(f"На этапе «{stage.name}» не назначена ни одна должность")


def _assert_submittable(subject, subject_id: str) -> None:
    """Отсечь повторную отправку того, по чему решение уже принято.

    Согласованный и отклонённый объекты заперты для правки
    (``Approvable.assert_editable``), и отправлять их заново нечего: круг
    прошёл бы по тому же самому содержимому. Штатный путь — вернуть на
    доработку, и текст ошибки говорит именно это.

    ``pending`` СЮДА НЕ ПОПАДАЕТ намеренно, хотя тоже неправим: «уже на
    согласовании» — другой разговор, и отвечает на него ``AlreadyInApproval``
    ниже, по частичному уникальному индексу. Индекс, а не проверка здесь,
    потому что он же закрывает гонку двух одновременных отправок; дублировать
    его условием значило бы завести второй источник правды с худшими
    гарантиями.
    """
    state = (subject.model.objects.filter(pk=subject_id)
             .values_list("approval_state", flat=True).first())
    # ``None`` — объекта нет. Ронять здесь нечем помочь: процесс всё равно
    # не на что заводить, и об этом внятнее скажет ``facts``/``describe``
    # дальше по коду, каждый про своё.
    if state is None or state in ApprovalState.editable():
        return
    if state == ApprovalState.PENDING:
        return

    # Безличное «принято решение», а не «уже согласован»: род подставляемой
    # подписи заранее неизвестен («Бюджет» согласован, «Заявка» согласована),
    # и склеить её с прилагательным нельзя, не заведя грамматику на каждый
    # согласуемый тип.
    raise SubjectLocked(
        f"По «{subject.label}» уже принято решение "
        f"({ApprovalState(state).label.lower()}) — чтобы отправить заново, "
        f"верните объект на доработку"
    )


def _select_stages(stages, facts: dict, *, subject, route):
    """Отобрать ветки маршрута под факты объекта, переведя отказы в 409.

    Обе ошибки ``conditions`` — про настройку маршрута, но прочтёт их
    пользователь, нажавший «отправить на согласование». Поэтому текст
    называет и объект, и то, ЧТО не сошлось: иначе по сообщению «не сошлось
    ни одно условие» невозможно понять, к кому идти.
    """
    try:
        return conditions.select_stages(stages, facts)
    except conditions.NoBranchMatched as exc:
        raise RouteUnusable(
            f"«{subject.label}»: в маршруте «{route.name}» на шаге "
            f"{exc.order} нет ветки под этот объект ({_facts_hint(exc.facts)}) "
            f"— добавьте ветку или этап «иначе»"
        ) from exc
    except conditions.ConditionError as exc:
        raise RouteUnusable(
            f"Маршрут «{route.name}» настроен неверно: {exc}") from exc


def _facts_hint(facts: dict) -> str:
    """Факты объекта одной строкой — чтобы в тексте ошибки было видно, ПОЧЕМУ
    ветка не нашлась. Без этого сообщение про несошедшееся условие бесполезно."""
    return ", ".join(f"{key}={value!r}" for key, value in sorted(facts.items())) \
        or "у объекта нет фактов для ветвления"


def _resolve_stages(selected, *, initiator_id: int | None,
                    subject_type: str, subject_id: str,
                    ) -> list[tuple[int, object, str, dict[int | None, list[int]]]]:
    """Проверить исполнимость отобранных этапов и развернуть согласующих.

    Возвращает ``(order, stage, matched_by, {position_id: user_ids})``.

    Здесь же ``ApproverKind`` превращается в конкретные id: дальше движок
    работает со списком пользователей и про вид согласующих не знает — ровно
    как он не знает про условия после ``_select_stages``. Поэтому
    ``ApprovalTask`` создаётся один раз, на запуске, и «инициатор» не
    пересчитывается на каждом решении.

    Проверяется на ЗАПУСКЕ, а не при сохранении маршрута: между настройкой
    и запуском проходит время, за которое согласующий успевает уволиться.
    Проверяются только ОТОБРАННЫЕ этапы — уволившийся согласующий в ветке,
    которая к этому объекту не относится, запуску не мешает.
    """
    plan: list[tuple[int, object, str, dict[int | None, list[int]]]] = []
    all_ids: set[int] = set()
    for item in selected:
        stage = item.stage
        approvers_by_position = _approver_ids(
            stage, initiator_id=initiator_id,
            subject_type=subject_type, subject_id=subject_id)
        all_ids.update(
            user_id for user_ids in approvers_by_position.values()
            for user_id in user_ids
        )
        plan.append((stage.order, stage, item.matched_by, approvers_by_position))

    active = _active_user_ids(all_ids)
    for _, stage, _, approvers_by_position in plan:
        user_ids = [
            user_id for ids in approvers_by_position.values()
            for user_id in ids
        ]
        if stage.approver_kind == ApproverKind.INITIATOR:
            if not any(user_id in active for user_id in user_ids):
                raise RouteUnusable(
                    f"Этап «{stage.name}» подписывает инициатор, но его "
                    f"учётная запись неактивна"
                )
        elif len(active.intersection(user_ids)) != len(user_ids):
            # HR filters inactive accounts while resolving positions.  Keep a
            # final check here for the small window before tasks are written:
            # every generated task must be executable, including ALL quorum.
            raise RouteUnusable(
                f"На этапе «{stage.name}» есть неактивный согласующий — "
                f"проверьте должности и связанные учётные записи"
            )
    return plan


def _approver_ids(stage, *, initiator_id: int | None,
                  subject_type: str, subject_id: str) -> dict[int | None, list[int]]:
    """Кому адресовать запросы этого этапа — по виду согласующих.

    Должности берутся из маршрута и разворачиваются через HR; этап
    ``INITIATOR`` — один инициатор процесса; ``USERS`` — список из маршрута
    как есть; ``SUBJECT`` — то, что назвал объект по ключу этапа. Ключ
    группировки — должность; у трёх остальных видов её нет (``None``), и
    кворум считается по всему этапу.

    Настройки, которых у вида быть не может (должности у инициатора), не
    объединяются, а запрещены на сохранении (``route_service``): молча
    исполнить то, чего администратор не мог задать через интерфейс, — худший
    из вариантов.
    """
    if stage.approver_kind == ApproverKind.INITIATOR:
        if initiator_id is None:
            raise RouteUnusable(
                f"Этап «{stage.name}» подписывает инициатор, но согласование "
                f"запущено без инициатора"
            )
        return {None: [initiator_id]}

    if stage.approver_kind == ApproverKind.USERS:
        user_ids = [int(uid) for uid in dict.fromkeys(stage.user_ids or [])]
        if not user_ids:
            raise RouteUnusable(
                f"На этапе «{stage.name}» не назван ни один согласующий")
        return {None: user_ids}

    if stage.approver_kind == ApproverKind.SUBJECT:
        user_ids = registry.approvers_for(subject_type, subject_id, stage.approver_key)
        if not user_ids:
            raise RouteUnusable(
                f"На этапе «{stage.name}» объект не назвал ни одного "
                f"согласующего («{stage.approver_key}») — заполните его в "
                f"объекте или измените этап маршрута"
            )
        return {None: user_ids}

    position_ids = [row.position_id for row in stage.roles.all()]
    if not position_ids:
        raise RouteUnusable(
            f"На этапе «{stage.name}» не назначена ни одна должность"
        )
    resolved = hr.resolve_position_users(position_ids)
    missing = [position_id for position_id in position_ids
               if not resolved.get(position_id)]
    if missing:
        raise RouteUnusable(
            f"На этапе «{stage.name}» нет активного сотрудника с активной "
            f"учётной записью для должности: " + ", ".join(map(str, missing))
        )
    return {
        position_id: list(dict.fromkeys(resolved[position_id]))
        for position_id in position_ids
    }


def _active_user_ids(user_ids) -> set[int]:
    """Кто из перечисленных — действующий пользователь платформы.

    Ошибку ``users`` НЕ глушим: здесь решается, кто вправе согласовать, и
    молча считать всех активными значило бы пропустить запуск маршрута,
    двигать который некому.
    """
    ids = list(user_ids)
    if not ids:
        return set()
    briefs = users.get_users_brief(ids)
    return {row["id"] for row in briefs if row.get("is_active")}


# ═══════════════════════════════════════════════════════════════════════
# Решение
# ═══════════════════════════════════════════════════════════════════════

def stage_votes(process: ApprovalProcess, stage: ApprovalProcessStage) -> bool:
    """Выбирает ли согласующий этого этапа вариант (исходный или альтернатива).

    Маршрут называет выбирающих признаком ``votes_option`` (модуль БЗО, D-25:
    ФД и ГД). Нет признака ни у одного этапа снимка — выбирает каждый этап
    (ТЗ §12.4, так было до признака).
    """
    if stage.votes_option:
        return True
    return not process.stages.filter(votes_option=True).exists()


def voting_stages_now(process: ApprovalProcess) -> bool:
    """Идёт ли сейчас группа, где выбирают вариант, — для карточки процесса."""
    if process.current_order is None:
        return False
    current = process.stages.filter(order=process.current_order)
    return any(stage_votes(process, stage) for stage in current)


@transaction.atomic
def act(*, task_id: int, actor_id: int, decision: str,
        comment: str = "", option_key: str = "") -> ApprovalProcess:
    """Принять решение по запросу и продвинуть процесс.

    ``option_key`` — ключ варианта, когда предметная аппка предложила выбор
    (``registry.options_for``): «согласовать» тогда означает «согласовать
    ЭТОТ вариант». Голос хранится в запросе и уходит предметной аппке
    (``on_option``); какой вариант в итоге принят, решает она сама по
    голосам (``interface.final_option``).

    Возвращает процесс в состоянии ПОСЛЕ решения.
    """
    if decision not in DECISIONS:
        raise SignoffError(f"Неизвестное решение: {decision}")

    task = (ApprovalTask.objects
            .select_related("stage", "stage__process")
            .filter(pk=task_id).first())
    if task is None:
        raise Http404("Запрос на согласование не найден")
    if task.user_id != actor_id:
        # 409, а не 403: сам факт существования запроса не секрет, а
        # «это не ваш запрос» — состояние данных, не нехватка прав.
        raise NotAnApprover("Этот запрос адресован другому согласующему")

    # Блокировка ПОСЛЕ проверок и до любых записей: дальше идут решения,
    # опирающиеся на состояние остальных этапов процесса.
    process = _lock(task.stage.process_id)
    if process.state != ProcessState.PENDING:
        raise ProcessClosed(
            f"Согласование уже завершено ({process.get_state_display()})"
        )
    # Перечитываем задачу под блокировкой — между первым чтением и
    # блокировкой её мог закрыть параллельный запрос.
    task.refresh_from_db()
    if task.state != TaskState.PENDING:
        raise ProcessClosed("По этому запросу решение уже принято")

    stage = task.stage
    flags = resolution.flags_of(process)
    # BR-061, вторая линия: маршрут с запретом самосогласования автору задач
    # не ставит, но задача могла появиться до включения флага. Этап «подпись
    # инициатора» — исключение по определению.
    if (flags["forbid_self_approval"] and actor_id == process.initiator_id
            and stage.approver_kind != ApproverKind.INITIATOR):
        raise SelfApprovalForbidden(
            "Нельзя согласовать документ, автором которого вы являетесь. "
            "Решение по нему примет другой согласующий.")
    # BR-060: отказ и возврат — с пояснением не короче, чем требует маршрут.
    minimum = int(flags["reject_comment_min"] or 0)
    if decision in (REJECT, REWORK) and minimum and len(comment.strip()) < minimum:
        raise CommentTooShort(
            f"Комментарий слишком короткий: при отказе и возврате на доработку "
            f"нужно не меньше {minimum} символов. Опишите причину — её увидит "
            f"автор документа.")
    # ДО любых записей: отказ по нехватке документа не должен оставлять за
    # собой закрытую задачу. Файл прикладывается заранее, отдельным
    # эндпоинтом (``services/attachments.py``) — грузить его внутри этой
    # транзакции значило бы держать блокировку процесса на время загрузки
    # в S3.
    if (decision == APPROVE and stage.requires_attachment
            and not task.file_id):
        raise AttachmentRequired(
            f"На этапе «{stage.name}» согласование возможно только с "
            f"приложенным документом — сначала загрузите PDF"
        )
    # Тот же гейт, что у документа, и по тем же правилам: только на согласовании,
    # ДО любых записей. ``strip()`` — пробел не пояснение; ровно так же пустой
    # комментарий отличает от заполненного форма (``schemas.Decision``).
    if (decision == APPROVE and stage.requires_comment
            and not comment.strip()):
        raise CommentRequired(
            f"На этапе «{stage.name}» согласование возможно только с "
            f"пояснением — напишите комментарий к решению"
        )
    # Требование к объекту — по тем же правилам: только на согласовании и
    # ДО записи. Что именно не сделано, объясняет предметная аппка — её
    # текст и уходит человеку.
    if decision == APPROVE and stage.requirement_key:
        process = stage.process
        reason = registry.check_requirement_for(
            process.subject_type, process.subject_id, stage.requirement_key)
        if reason:
            raise SubjectRequirementUnmet(
                f"На этапе «{stage.name}» сначала нужно: {reason}")
    # Выбор варианта — тем же порядком: только на согласовании и ДО записи.
    chosen_key, chosen_label = "", ""
    if decision == APPROVE and stage_votes(process, stage):
        options = registry.options_for(process.subject_type, process.subject_id)
        if len(options) > 1:
            labels = {item["key"]: item["label"] for item in options}
            if not option_key:
                raise OptionRequired(
                    "К документу поданы альтернативы — выберите, какой вариант "
                    "вы согласуете: исходный или одну из альтернатив")
            if option_key not in labels:
                raise OptionRejected(
                    "Этого варианта больше нет среди предложенных — обновите "
                    "страницу и выберите снова")
            reason = registry.check_option_for(
                process.subject_type, process.subject_id, option_key)
            if reason:
                raise OptionRejected(reason)
            chosen_key, chosen_label = option_key, labels[option_key]

    task.state = (TaskState.APPROVED if decision == APPROVE
                  else _DECISION_OUTCOME[decision][0])
    task.comment = comment
    task.option_key = chosen_key
    task.option_label = chosen_label[:300]
    task.acted_at = _now()
    task.save(update_fields=["state", "comment", "option_key", "option_label", "acted_at"])
    if chosen_key:
        # Доменная запись голоса (D-26) — в этой же транзакции: упади она,
        # откатится и решение.
        registry.on_option_for(process.subject_type, process.subject_id,
                               stage.order, actor_id, chosen_key)

    payload = {"stage": stage.name, "task_id": task.pk, "comment": comment,
               # Какой именно документ подписан — часть ответа на «на
               # основании чего согласовано», и искать его в другом месте
               # журнала не должно быть нужно.
               "file_id": task.file_id or None}
    if chosen_key:
        payload.update({"option_key": chosen_key, "option_label": chosen_label})
    _log(process, _EVENT_KIND[decision], actor_id=actor_id, payload=payload)
    _emit(process, "task_decided", {"task_id": task.pk, "decision": decision,
                                    "actor_id": actor_id, "stage": stage.name})

    if decision != APPROVE:
        _close_by_decision(process, stage, decision=decision,
                           actor_id=actor_id, comment=comment)
        return process

    if _settle_stage(stage):
        _advance(process, actor_id=actor_id)
    return process


def _settle_stage(stage: ApprovalProcessStage) -> bool:
    """Закрыть этап, если его кворум набран. ``True`` — этап согласован.

    Отказ здесь не обрабатывается: он до этой функции не доходит (``act``
    уводит его в ``_reject``), потому что отказ решает судьбу всего
    процесса, а не одного этапа.
    """
    tasks = list(stage.tasks.all())
    tasks_by_position: dict[int | None, list[ApprovalTask]] = {}
    for item in tasks:
        tasks_by_position.setdefault(item.position_id, []).append(item)

    # A selected HR position represents one required role in a stage.  The
    # stage proceeds only after every selected role has met its quorum: ``any``
    # means one current holder of *each* position; ``all`` means every current
    # holder of *each* position.  Legacy tasks without a position snapshot stay
    # in one group, preserving the semantics of processes already in flight.
    def role_settled(role_tasks: list[ApprovalTask]) -> bool:
        approved = sum(task.state == TaskState.APPROVED for task in role_tasks)
        return bool(approved) if stage.quorum == Quorum.ANY else approved == len(role_tasks)

    # Once one holder has approved an ``any`` role, the other holders have no
    # further say in this stage.  Leave their tasks pending while another role
    # is still awaited and one of them could reject a role that already passed.
    if stage.quorum == Quorum.ANY:
        for position_id, role_tasks in tasks_by_position.items():
            if role_settled(role_tasks):
                stage.tasks.filter(
                    position_id=position_id, state=TaskState.PENDING,
                ).update(state=TaskState.SKIPPED)

    enough = all(role_settled(role_tasks)
                 for role_tasks in tasks_by_position.values())

    if not enough:
        return False

    stage.state = StageState.APPROVED
    stage.decided_at = _now()
    stage.save(update_fields=["state", "decided_at"])
    # При кворуме «достаточно одного» остальные запросы этапа больше не
    # нужны — гасим, чтобы они исчезли из чужих списков «ждёт решения».
    stage.tasks.filter(state=TaskState.PENDING).update(state=TaskState.SKIPPED)
    return True


def _advance(process: ApprovalProcess, *, actor_id: int | None) -> bool:
    """Перейти к следующей группе этапов или завершить процесс согласованием.

    Группа, которая при открытии закрылась сама (все её группы должностей
    пропущены при самосогласовании), сразу уступает место следующей — поэтому
    цикл. ``True`` — открыта следующая группа или процесс завершён; тогда же и
    уведомления, иначе (в группе ещё есть незакрытые параллельные этапы) —
    ни того, ни другого, как и прежде.
    """
    moved = False
    while True:
        current = list(process.stages.filter(order=process.current_order))
        if not all(stage.state == StageState.APPROVED for stage in current):
            break  # в текущей группе ещё есть незакрытые параллельные этапы

        next_order = (process.stages
                      .filter(order__gt=process.current_order)
                      .order_by("order")
                      .values_list("order", flat=True).first())
        if next_order is None:
            _finish(process, ProcessState.APPROVED, actor_id=actor_id)
            return True

        _log(process, "stage_activated", actor_id=actor_id,
             payload={"order": next_order})
        _open_group(process, next_order, actor_id=actor_id)
        moved = True

    if moved:
        _notify_active_stages(process)
    return moved


def _open_group(process: ApprovalProcess, order: int, *,
                actor_id: int | None) -> None:
    """Сделать группу этапов текущей и активной.

    С ``lazy_resolution`` этап здесь же получает исполнителей (по снимку
    своей настройки, на сегодня); не нашлось — «Нет исполнителя». Этап без
    единой задачи (все его группы пропущены при самосогласовании) согласуется
    сразу — ждать ему некого.
    """
    flags = resolution.flags_of(process)
    now = _now()
    process.current_order = order
    process.save(update_fields=["current_order", "updated_at"])
    for stage in process.stages.filter(order=order):
        if flags["lazy_resolution"] and not _materialize(process, stage, flags=flags):
            continue  # «Нет исполнителя» — этап ждёт
        stage.state = StageState.ACTIVE
        stage.activated_at = now
        stage.save(update_fields=["state", "activated_at"])
        if not stage.tasks.exists():
            _approve_empty_stage(process, stage, actor_id=actor_id)


def _approve_empty_stage(process: ApprovalProcess, stage: ApprovalProcessStage, *,
                         actor_id: int | None) -> None:
    stage.state = StageState.APPROVED
    stage.decided_at = _now()
    stage.save(update_fields=["state", "decided_at"])
    _log(process, "stage_auto_approved", actor_id=actor_id,
         payload={"stage": stage.name, "order": stage.order})


def _materialize(process: ApprovalProcess, stage: ApprovalProcessStage, *,
                 flags: dict) -> bool:
    """Исполнители этапа ленивого маршрута — сейчас, по снимку этапа.

    У группы нет исполнителя — этап «Нет исполнителя» (ТЗ §16.1 п.5): задач
    не ставим вовсе, пока не найдутся все (кворум считается по каждой
    группе), и уведомляем тех, кто может назначить, — один раз, при переходе
    в это состояние, а не на каждой повторной попытке. ``True`` — задачи
    поставлены (или ставить их некому по предсогласованию и самосогласованию).
    """
    try:
        outcome = resolution.resolve_process_stage(
            stage, initiator_id=process.initiator_id,
            subject_type=process.subject_type, subject_id=process.subject_id,
            flags=flags,
            exclude_positions=[row["position_id"] for row in (process.preapproved or [])])
    except resolution.StageNotConfigured as exc:
        raise RouteUnusable(str(exc)) from exc

    if outcome.missing:
        if stage.state != StageState.NO_EXECUTOR:
            stage.state = StageState.NO_EXECUTOR
            stage.save(update_fields=["state"])
            _log(process, "no_executor", actor_id=None, payload={
                "stage": stage.name, "order": stage.order,
                "position_ids": [key for key in outcome.missing if key is not None]})
            _notify_positions(flags["no_executor_notify_position_ids"], process, {
                "type": "signoff.no_executor", "stage": stage.name})
        return False
    _create_tasks(process, stage, outcome, flags=flags)
    return True


def _create_tasks(process: ApprovalProcess, stage: ApprovalProcessStage,
                  outcome: "resolution.Resolution", *, flags: dict) -> None:
    """Задачи этапа по разрешённым группам + следы самосогласования."""
    ApprovalTask.objects.bulk_create([
        ApprovalTask(stage=stage, user_id=user_id, position_id=position_id)
        for position_id, user_ids in outcome.groups.items()
        for user_id in user_ids
    ])
    if outcome.escalated:
        _log(process, "self_approval_escalated", actor_id=None, payload={
            "stage": stage.name, "order": stage.order,
            "position_ids": [key for key in outcome.escalated if key is not None],
            "escalation_position_id": flags.get("escalation_position_id")})
    if outcome.skipped:
        _log(process, "self_approval_skipped", actor_id=None, payload={
            "stage": stage.name, "order": stage.order,
            "position_ids": [key for key in outcome.skipped if key is not None]})
        _notify_positions(flags["self_skip_notify_position_ids"], process, {
            "type": "signoff.self_approval_skipped", "stage": stage.name})


@transaction.atomic
def retry_no_executor(process_id: int, *, actor_id: int | None = None) -> int:
    """Ещё раз поискать исполнителей этапам «Нет исполнителя» текущей группы.

    Зовётся периодической задачей и ручкой администратора: назначили
    сотрудника или временного исполнителя — этап оживает. Возвращает, скольким
    этапам исполнитель нашёлся.
    """
    process = _lock(process_id)
    if process.state != ProcessState.PENDING:
        return 0
    flags = resolution.flags_of(process)
    now = _now()
    found = 0
    for stage in process.stages.filter(order=process.current_order,
                                       state=StageState.NO_EXECUTOR):
        if not _materialize(process, stage, flags=flags):
            continue
        found += 1
        stage.state = StageState.ACTIVE
        stage.activated_at = now
        stage.save(update_fields=["state", "activated_at"])
        _log(process, "executors_found", actor_id=actor_id,
             payload={"stage": stage.name, "order": stage.order})
        if not stage.tasks.exists():
            _approve_empty_stage(process, stage, actor_id=actor_id)
    if found and not _advance(process, actor_id=actor_id):
        _notify_active_stages(process)
    return found


def pending_no_executor_process_ids() -> list[int]:
    """Процессы, которые ждут исполнителя, — для периодической повторной попытки."""
    return list(ApprovalProcess.objects
                .filter(state=ProcessState.PENDING,
                        stages__state=StageState.NO_EXECUTOR)
                .values_list("pk", flat=True).distinct())


def _close_by_decision(process: ApprovalProcess, stage: ApprovalProcessStage, *,
                       decision: str, actor_id: int | None,
                       comment: str = "") -> None:
    """Отказ или возврат на доработку закрывают ВЕСЬ процесс с этого этапа.

    Оба решают судьбу процесса целиком, а не одного этапа: продолжать
    собирать подписи под документом, который уже отправили переделывать,
    незачем. Поэтому и код один — расходятся они только тройкой состояний
    (``_DECISION_OUTCOME``) и тем, что из неё выведет ``_finish`` для
    предметного объекта.
    """
    # Состояние задачи из этой же тройки уже проставил ``act`` — здесь
    # закрываются только этап и процесс.
    _, stage_state, process_state = _DECISION_OUTCOME[decision]

    stage.state = stage_state
    stage.decided_at = _now()
    stage.save(update_fields=["state", "decided_at"])

    # Всё, до чего дело не дошло, — «не потребовалось», а не «отклонено»:
    # в карточке должно быть видно, кто именно принял решение.
    ApprovalTask.objects.filter(
        stage__process=process, state=TaskState.PENDING,
    ).update(state=TaskState.SKIPPED)
    process.stages.filter(
        state__in=(StageState.WAITING, StageState.ACTIVE, StageState.NO_EXECUTOR),
    ).update(state=StageState.SKIPPED)

    _finish(process, process_state, actor_id=actor_id, comment=comment)


@transaction.atomic
def cancel(*, process_id: int, actor_id: int | None = None) -> ApprovalProcess:
    """Отозвать согласование (инициатором или администратором).

    Объект возвращается в черновик — отозванное согласование не отказ, и
    отправить объект заново можно сразу.
    """
    process = _lock(process_id)
    if process.state != ProcessState.PENDING:
        raise ProcessClosed(
            f"Согласование уже завершено ({process.get_state_display()})"
        )

    ApprovalTask.objects.filter(
        stage__process=process, state=TaskState.PENDING,
    ).update(state=TaskState.SKIPPED)
    process.stages.filter(
        state__in=(StageState.WAITING, StageState.ACTIVE, StageState.NO_EXECUTOR),
    ).update(state=StageState.SKIPPED)

    _finish(process, ProcessState.CANCELLED, actor_id=actor_id)
    return process


@transaction.atomic
def reopen(*, process_id: int, actor_id: int | None = None,
           comment: str = "") -> ApprovalProcess:
    """Вернуть на доработку объект, по которому круг уже ЗАКРЫТ.

    Второй вход в доработку — первый это решение ``REWORK`` по своему
    запросу, пока согласование идёт. Здесь решение уже принято, и объект
    заперт им: согласованный документ не правят, отклонённый тоже
    (``Approvable.assert_editable``). Эта функция — единственный способ его
    отпереть, поэтому она есть вообще: без неё «согласовано» стало бы
    состоянием, из которого нет выхода, а любая опечатка в согласованном
    договоре требовала бы завести рядом второй.

    Кто вправе — решает ВЬЮХА (``views.ProcessReworkView``): движок не знает
    про роли, а «свой ли это процесс» — вопрос HTTP-слоя, ровно как у
    ``cancel``.

    Круг при этом не воскресает: процесс переходит в ``REWORK``, его этапы
    остаются такими, какими были на момент решения, и доработанный объект
    отправляют ЗАНОВО — новым процессом. Продолжать старый нельзя: маршрут
    и факты объекта на новом запуске уже другие, а согласующие прошлого
    круга видели прошлый документ.

    ``finished_at`` НЕ переписывается: круг закончился тогда, когда его
    закончило решение, а не когда кто-то попросил переделать. Момент
    возврата хранит событие журнала (``reopened``) — вместе с тем, из какого
    состояния вернули, и комментарием, ради которого всё и затевалось.
    """
    process = _lock(process_id)

    if process.state == ProcessState.PENDING:
        raise ProcessStillRunning(
            "Согласование ещё идёт: вернуть объект на доработку может "
            "согласующий своим решением, а инициатор — отозвать заявку"
        )
    if process.state not in (ProcessState.APPROVED, ProcessState.REJECTED):
        # ``rework`` и ``cancelled`` — объект и так открыт для правки.
        raise ProcessClosed(
            f"Объект уже открыт для правки ({process.get_state_display()})"
        )

    previous = process.state
    process.state = ProcessState.REWORK
    process.save(update_fields=["state", "updated_at"])

    _log(process, "reopened", actor_id=actor_id,
         payload={"from": previous, "comment": comment})
    _apply_outcome(process, ProcessState.REWORK)
    _notify_initiator(process)
    return process


def _finish(process: ApprovalProcess, state: str, *, actor_id: int | None,
            comment: str = "") -> None:
    """Закрыть процесс и сообщить результат предметной аппке.

    Колбэк вызывается ЗДЕСЬ, внутри транзакции движка: предметный объект и
    процесс обязаны перейти в согласованные состояния атомарно. Вынести
    колбэк в ``on_commit`` значило бы допустить окно, в котором процесс уже
    согласован, а бюджет ещё нет — и падение колбэка в этом окне уже никто
    не откатит.
    """
    process.state = state
    process.current_order = None
    process.finished_at = _now()
    process.save(update_fields=["state", "current_order", "finished_at",
                                "updated_at"])
    _log(process, state, actor_id=actor_id, payload={"comment": comment})
    _apply_outcome(process, state)
    _notify_initiator(process)


# Во что итог процесса переводит ПРЕДМЕТНЫЙ объект. «На доработке», а не
# «черновик»: правятся оба одинаково, но в списке это разные вещи — черновик
# никто не смотрел, а этот объект вернули с замечаниями. Отозванный, наоборот,
# неотличим от черновика: отзыв — не решение, и показывать его как «вернули»
# значило бы приписать согласующим то, чего они не говорили.
_SUBJECT_STATE_BY_OUTCOME = {
    ProcessState.APPROVED: ApprovalState.APPROVED,
    ProcessState.REJECTED: ApprovalState.REJECTED,
    ProcessState.REWORK: ApprovalState.REWORK,
    ProcessState.CANCELLED: ApprovalState.DRAFT,
}


def _apply_outcome(process: ApprovalProcess, state: str) -> None:
    """Сообщить итог предметной аппке и проставить объекту ``approval_state``.

    Отдельно от ``_finish`` потому, что итог процесса применяется дважды:
    при завершении круга и при ``reopen`` — возврате на доработку УЖЕ
    закрытого. Держать эту пару (колбэк + состояние объекта) в одном месте
    обязательно: разъехавшись, они дают согласованный договор, который
    числится черновиком, или наоборот.
    """
    subject = registry.get_subject(process.subject_type)
    callback = {
        ProcessState.APPROVED: subject.on_approved,
        ProcessState.REJECTED: subject.on_rejected,
        ProcessState.REWORK: subject.on_rework,
        ProcessState.CANCELLED: subject.on_cancelled,
    }.get(state)
    if callback is not None:
        callback(registry.native_id(process.subject_type, process.subject_id))

    _set_subject_state(process.subject_type, process.subject_id,
                       _SUBJECT_STATE_BY_OUTCOME[state])


# ═══════════════════════════════════════════════════════════════════════
# Служебное
# ═══════════════════════════════════════════════════════════════════════

def _lock(process_id: int) -> ApprovalProcess:
    """Взять процесс с ``SELECT … FOR UPDATE``.

    Обязательно для любого перехода: решения читают состояние соседних
    этапов и на его основании завершают процесс. Без блокировки два
    согласующих, одновременно закрывающих последнюю параллельную пару
    этапов, оба увидят «все согласовали» и оба дёрнут ``on_approved``.
    """
    process = ApprovalProcess.objects.select_for_update().filter(pk=process_id).first()
    if process is None:
        raise Http404("Процесс согласования не найден")
    return process


def _set_subject_state(subject_type: str, subject_id: str, state: str) -> None:
    """Проставить ``approval_state`` предметному объекту.

    Пишет сам signoff — через класс модели, который предметная аппка отдала
    при регистрации (``Subject.model``; см. её докстринг о том, почему это
    не нарушает правило границ). Колонка объявлена примесью ``Approvable``,
    то есть принадлежит signoff: перекладывать её ведение на колбэк каждой
    предметной аппки значило бы размножить одну и ту же строчку по всем
    доменам и получить домен, который однажды забудет её написать.

    Доменные последствия — не здесь: их делает ``Subject.on_*`` (у договора
    это перевод собственного ``status`` по таблице переходов).

    ``update()``, а не ``save()``: сигналы и ``full_clean`` предметной
    модели тут не нужны и небезопасны — signoff не знает, что они делают.
    """
    subject = registry.get_subject(subject_type)
    updated = subject.model.objects.filter(pk=subject_id).update(
        approval_state=state)
    if not updated:
        # Строку удалили, пока шло согласование. Межаппного FK нет, каскад
        # не сработал — процесс остался висеть. Ронять на этом уже поздно
        # (решение принято), но в логе это должно быть видно.
        logger.warning("signoff: объект %s#%s не найден — approval_state=%s "
                       "не проставлен", subject_type, subject_id, state)


def _log(process: ApprovalProcess, kind: str, *, actor_id: int | None,
         payload: dict | None = None) -> None:
    ApprovalEvent.objects.create(process=process, kind=kind, actor_id=actor_id,
                                 payload=payload or {})


def _notify_active_stages(process: ApprovalProcess) -> None:
    """Уведомить тех, на ком сейчас висит решение."""
    user_ids = list(ApprovalTask.objects.filter(
        stage__process=process, stage__state=StageState.ACTIVE,
        state=TaskState.PENDING,
    ).values_list("user_id", flat=True))
    if not user_ids:
        return

    described = _describe(process)
    _notify(user_ids, {
        "type": "signoff.awaiting_you",
        "process_id": process.pk,
        "subject_type": process.subject_type,
        "subject_id": process.subject_id,
        "title": described.get("title"),
        "url": described.get("url"),
    })
    _emit(process, "stage_activated", {"user_ids": user_ids,
                                       "order": process.current_order})


def _notify_positions(position_ids, process: ApprovalProcess, extra: dict) -> None:
    """Уведомить держателей должностей (и их временных исполнителей) о
    событии процесса: «Нет исполнителя» — АДМ и ГД, пропуск самосогласования
    ГД — ФД (мастер-план БЗО, D-21/D-22). Нет должностей — никого."""
    user_ids = resolution.position_user_ids(position_ids)
    if not user_ids:
        return
    described = _describe(process)
    _notify(user_ids, {
        "process_id": process.pk,
        "subject_type": process.subject_type,
        "subject_id": process.subject_id,
        "title": described.get("title"),
        "url": described.get("url"),
        **extra,
    })


def _notify_initiator(process: ApprovalProcess) -> None:
    # Событие итога уходит владельцу объекта и без инициатора: свои ленты и
    # SSE предметная аппка ведёт по объекту, а не по человеку.
    _emit(process, str(process.state), {"initiator_id": process.initiator_id})
    if process.initiator_id is None:
        return
    described = _describe(process)
    _notify([process.initiator_id], {
        "type": f"signoff.{process.state}",
        "process_id": process.pk,
        "subject_type": process.subject_type,
        "subject_id": process.subject_id,
        "title": described.get("title"),
        "url": described.get("url"),
    })


def _emit(process: ApprovalProcess, kind: str, payload: dict) -> None:
    """Событие процесса — колбэку ``Subject.on_event`` предметной аппки.

    Те же правила, что у ``_notify``: после коммита (событие об откатившемся
    переходе — ложь) и best-effort (SSE или чужая лента не должны ронять
    согласование). Виды: ``stage_activated``, ``task_decided`` и итоговые
    состояния процесса (``approved``/``rejected``/``rework``/``cancelled``).
    """
    subject = registry.get_subject(process.subject_type)
    if subject.on_event is None:
        return
    body = {"process_id": process.pk, "state": str(process.state), **payload}
    subject_id = registry.native_id(process.subject_type, process.subject_id)

    def send() -> None:
        try:
            subject.on_event(subject_id, kind, body)
        except Exception:
            logger.warning("signoff: on_event(%s) для %s#%s упал",
                           kind, process.subject_type, subject_id, exc_info=True)

    transaction.on_commit(send)


def _describe(process: ApprovalProcess) -> dict:
    """Человекочитаемая карточка чужого объекта — через колбэк его аппки."""
    subject = registry.get_subject(process.subject_type)
    if subject.describe is None:
        return {"title": f"{subject.label} #{process.subject_id}", "url": None}
    try:
        return subject.describe(
            registry.native_id(process.subject_type, process.subject_id)) or {}
    except Exception:
        # Оформление карточки не должно ронять согласование.
        logger.warning("signoff: describe() для %s#%s упал",
                       process.subject_type, process.subject_id, exc_info=True)
        return {"title": f"{subject.label} #{process.subject_id}", "url": None}


#: Заголовок в центре уведомлений по событию (ТЗ §22): к заголовку документа
#: из ``describe`` предметной аппки.
_CENTER_TITLES = {
    "signoff.awaiting_you": "{title} ждёт вашего согласования",
    "signoff.approved": "{title} — согласовано",
    "signoff.rejected": "{title} — отклонено",
    "signoff.rework": "{title} — возвращено на доработку",
    "signoff.cancelled": "{title} — согласование отозвано",
    "signoff.no_executor": "{title}: этап «{stage}» ждёт исполнителя",
    "signoff.self_approval_skipped":
        "{title}: этап «{stage}» пропущен — автор документа и есть согласующий",
}


def _notify_center(user_ids: list[int], payload: dict) -> bool:
    """Уведомление через центр уведомлений (мастер-план БЗО, B1.2 / A1.5):
    колокольчик, e-mail, Telegram по выбору получателя.

    Запись — в транзакции согласования (откатилось решение — нет и
    уведомления), доставку центр ставит сам после коммита. Своя точка
    сохранения: сбой центра не роняет решение. ``False`` — центра нет или
    он выключен, и тогда уведомление идёт старым путём, через мессенджер.
    """
    from django.apps import apps as django_apps

    if not django_apps.is_installed("apps.notifications"):
        return False
    from apps.notifications import interface as notifications
    from htqweb.tenancy import current_company_or_none

    kind = payload.get("type") or "signoff.event"
    subject_type = str(payload.get("subject_type") or "")
    title = payload.get("title") or f"{subject_type} №{payload.get('subject_id')}"
    template = _CENTER_TITLES.get(kind, "{title}")
    try:
        with transaction.atomic():
            notifications.notify(
                recipients=user_ids, event=kind,
                title=template.format(title=title, stage=payload.get("stage", "")),
                url=payload.get("url") or f"/signoff/processes/{payload.get('process_id')}",
                company_slug=current_company_or_none(),
                target_type=subject_type,
                target_id=str(payload.get("subject_id") or ""),
                # Документы модуля БЗО — колокольчик и выбранные каналы (e-mail,
                # Telegram; ТЗ §22). Остальные предметы (кадры, заявки
                # конструктора, договоры) — только колокольчик, как было до
                # центра (план этапа 2, задача 1; решение 27.09).
                deliver=subject_type.startswith("bpp."))
    except ServiceDisabled:
        return False
    except Exception:
        logger.warning("signoff: центр уведомлений не принял уведомление", exc_info=True)
    return True


def _notify(user_ids: list[int], payload: dict) -> None:
    """Разослать уведомление, best-effort.

    Сначала — центр уведомлений (``_notify_center``). Нет его — мессенджер
    ПОСЛЕ коммита: ``on_commit`` — потому что рассылать по откатившейся
    транзакции нечего, согласующий получил бы запрос, которого нет.
    Проглатывание ошибок — потому что выключенный канал не повод отказать в
    согласовании (в отличие от выключенного ``users``, который решает, КТО
    согласует).
    """
    if _notify_center(user_ids, payload):
        return

    def send() -> None:
        try:
            messenger.dispatch_notification(user_ids, payload)
        except ServiceDisabled:
            logger.info("signoff: messenger выключен, уведомление не отправлено")
        except Exception:
            logger.warning("signoff: не удалось отправить уведомление",
                           exc_info=True)

    transaction.on_commit(send)
