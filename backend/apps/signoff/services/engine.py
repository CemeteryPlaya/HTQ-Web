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
from apps.signoff.services import conditions, registry
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


class CommentRequired(SignoffError):
    """Этап требует пояснение к решению, а комментарий пуст.

    Проверяется, как и ``AttachmentRequired``, только на СОГЛАСОВАНИИ: у
    отказа и возврата на доработку комментарий и так по смыслу обязателен
    (это и есть объяснение решения), а настойчивость формы здесь пришлась бы
    ровно на тот случай, где человек и без галочки пишет, зачем отклонил.
    Гейт нужен обратному — «согласовано» без единого слова, — поэтому стоит
    он на ``approve``.
    """


def _now() -> datetime:
    return datetime.now(_tz.utc)


# ═══════════════════════════════════════════════════════════════════════
# Запуск
# ═══════════════════════════════════════════════════════════════════════

@transaction.atomic
def start(*, subject_type: str, subject_id: int,
          initiator_id: int | None = None) -> ApprovalProcess:
    """Запустить согласование объекта по активному маршруту его типа."""
    subject = registry.get_subject(subject_type)  # UnknownSubject → 409/422

    route = (ApprovalRoute.objects
             .filter(subject_type=subject_type, is_active=True)
             .prefetch_related("stages__roles").first())
    if route is None:
        raise RouteNotConfigured(
            f"Для «{subject.label}» не настроен маршрут согласования"
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
    plan = _resolve_stages(selected, initiator_id=initiator_id)

    try:
        process = ApprovalProcess.objects.create(
            subject_type=subject_type, subject_id=subject_id,
            route_id=route.pk, initiator_id=initiator_id,
            state=ProcessState.PENDING, subject_facts=facts,
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
            requires_attachment=stage.requires_attachment,
            requires_comment=stage.requires_comment,
            state=StageState.ACTIVE if order == first_order else StageState.WAITING,
        )
        ApprovalTask.objects.bulk_create([
            ApprovalTask(stage=process_stage, user_id=user_id,
                         position_id=position_id)
            for position_id, user_ids in approvers_by_position.items()
            for user_id in user_ids
        ])

    process.current_order = first_order
    process.save(update_fields=["current_order", "updated_at"])

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

    if subject.on_started is not None:
        subject.on_started(subject_id)
    _set_subject_state(subject_type, subject_id, ApprovalState.PENDING)

    _notify_active_stages(process)
    return process


def _assert_submittable(subject, subject_id: int) -> None:
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


def _resolve_stages(selected, *,
                    initiator_id: int | None) -> list[tuple[int, object, str, dict[int | None, list[int]]]]:
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
        approvers_by_position = _approver_ids(stage, initiator_id=initiator_id)
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


def _approver_ids(stage, *, initiator_id: int | None) -> dict[int | None, list[int]]:
    """Кому адресовать запросы этого этапа.

    Названные поимённо согласующие берутся из маршрута; этап
    ``ApproverKind.INITIATOR`` разворачивается в одного инициатора процесса.
    Названные согласующие у такого этапа игнорируются намеренно, а не
    объединяются со инициатором: сочетание запрещено настройкой
    (``route_service._check_approver_kind``), и молча исполнить то, чего
    администратор не мог задать через интерфейс, — худший из вариантов.
    """
    if stage.approver_kind == ApproverKind.INITIATOR:
        if initiator_id is None:
            raise RouteUnusable(
                f"Этап «{stage.name}» подписывает инициатор, но согласование "
                f"запущено без инициатора"
            )
        return {None: [initiator_id]}

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

@transaction.atomic
def act(*, task_id: int, actor_id: int, decision: str,
        comment: str = "") -> ApprovalProcess:
    """Принять решение по запросу и продвинуть процесс.

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

    task.state = (TaskState.APPROVED if decision == APPROVE
                  else _DECISION_OUTCOME[decision][0])
    task.comment = comment
    task.acted_at = _now()
    task.save(update_fields=["state", "comment", "acted_at"])

    _log(process, _EVENT_KIND[decision], actor_id=actor_id,
         payload={"stage": stage.name, "task_id": task.pk, "comment": comment,
                  # Какой именно документ подписан — часть ответа на «на
                  # основании чего согласовано», и искать его в другом месте
                  # журнала не должно быть нужно.
                  "file_id": task.file_id or None})

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


def _advance(process: ApprovalProcess, *, actor_id: int | None) -> None:
    """Перейти к следующей группе этапов или завершить процесс согласованием."""
    current = list(process.stages.filter(order=process.current_order))
    if not all(stage.state == StageState.APPROVED for stage in current):
        return  # в текущей группе ещё есть незакрытые параллельные этапы

    next_order = (process.stages
                  .filter(order__gt=process.current_order)
                  .order_by("order")
                  .values_list("order", flat=True).first())

    if next_order is None:
        _finish(process, ProcessState.APPROVED, actor_id=actor_id)
        return

    process.stages.filter(order=next_order).update(state=StageState.ACTIVE)
    process.current_order = next_order
    process.save(update_fields=["current_order", "updated_at"])
    _log(process, "stage_activated", actor_id=actor_id,
         payload={"order": next_order})
    _notify_active_stages(process)


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
        state__in=(StageState.WAITING, StageState.ACTIVE),
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
        state__in=(StageState.WAITING, StageState.ACTIVE),
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
        callback(process.subject_id)

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


def _set_subject_state(subject_type: str, subject_id: int, state: str) -> None:
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


def _notify_initiator(process: ApprovalProcess) -> None:
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


def _describe(process: ApprovalProcess) -> dict:
    """Человекочитаемая карточка чужого объекта — через колбэк его аппки."""
    subject = registry.get_subject(process.subject_type)
    if subject.describe is None:
        return {"title": f"{subject.label} #{process.subject_id}", "url": None}
    try:
        return subject.describe(process.subject_id) or {}
    except Exception:
        # Оформление карточки не должно ронять согласование.
        logger.warning("signoff: describe() для %s#%s упал",
                       process.subject_type, process.subject_id, exc_info=True)
        return {"title": f"{subject.label} #{process.subject_id}", "url": None}


def _notify(user_ids: list[int], payload: dict) -> None:
    """Разослать уведомление ПОСЛЕ коммита, best-effort.

    ``on_commit`` — потому что рассылать по откатившейся транзакции нечего:
    согласующий получил бы запрос, которого нет. Проглатывание ошибок —
    потому что выключенный messenger не повод отказать в согласовании
    (в отличие от выключенного ``users``, который решает, КТО согласует).
    """
    def send() -> None:
        try:
            messenger.dispatch_notification(user_ids, payload)
        except ServiceDisabled:
            logger.info("signoff: messenger выключен, уведомление не отправлено")
        except Exception:
            logger.warning("signoff: не удалось отправить уведомление",
                           exc_info=True)

    transaction.on_commit(send)
