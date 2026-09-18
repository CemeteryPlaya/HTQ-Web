"""Instance CRUD around the workflow runtime.

Ported from ``services/requests/app/api/v1/instances.py`` and the query half
of ``InstanceRepository``. The lifecycle transitions themselves
(submit/act/cancel/recall) live in ``request_runtime`` — this module only
covers creating, listing, reading and editing a draft.
"""

from __future__ import annotations

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import Http404

from apps.core.services import ServiceDisabled
from apps.signoff import interface as signoff

from ..models import (
    RequestActivity, RequestFormTemplate, RequestFormTemplateVersion,
    RequestInstance, RequestStatus, RequestWatcher,
)
from . import request_runtime
from .request_runtime import RuntimeConflict
from .form_schema import validate_form_schema
from .template_settings import settings_for_template
from . import quotes


def get_or_404(instance_id: int) -> RequestInstance:
    instance = RequestInstance.objects.filter(pk=instance_id).first()
    if instance is None:
        raise Http404("Request not found")
    return instance


def can_view(instance: RequestInstance, token) -> bool:
    """Кому видна карточка заявки.

    Причастным — и только им: инициатору (его заявка), наблюдателю в копии,
    согласующему (в любом круге, в том числе закрытом — он вправе видеть,
    что подписывал) и администратору платформы. Остальным заявка не видна:
    в значениях формы лежат суммы, поставщики и обоснование, и «знать id»
    правом на них быть не должно.

    Отдельно от ``list_for_user``: список всегда отвечает по «ящику»
    спрашивающего и чужого в принципе не покажет, а карточку открывают по
    прямой ссылке — там правило нужно своё.
    """
    if token.is_elevated or instance.initiator_id == token.user_id:
        return True
    if RequestWatcher.objects.filter(request=instance,
                                     user_id=token.user_id).exists():
        return True
    try:
        return signoff.is_participant(token.user_id,
                                      RequestInstance.SIGNOFF_SUBJECT_TYPE,
                                      instance.pk)
    except ServiceDisabled:
        # Выключенный signoff не должен расширять видимость: молчаливое
        # «да» открыло бы чужие заявки ровно на время обслуживания.
        return False


def get_visible_or_404(instance_id: int, *, token) -> RequestInstance:
    """Карточка по тем же правилам, что список, — и 404, а не 403.

    Чужая заявка отвечает «не найдено»: 403 подтвердил бы, что заявка с
    таким id существует. Тот же приём, что у signoff
    (``views._visible_process_or_404``).
    """
    instance = get_or_404(instance_id)
    if not can_view(instance, token):
        raise Http404("Request not found")
    return instance


def list_for_user(user_id: int, *, box: str = "inbox") -> list[RequestInstance]:
    """The four Lark-parity mailboxes.

    * ``sent``  — requests the user initiated (Отправленные)
    * ``cc``    — requests the user follows as a watcher (Копия)
    * ``done``  — requests the user has already acted on (Готово)
    * ``inbox`` — pending requests awaiting the user's action (Список дел)

    Any unknown value falls through to ``inbox``, matching the original's
    ``else`` branch rather than erroring — the box name comes from a UI tab.

    ``inbox`` и ``done`` — вопросы к движку согласования: кто должен решить
    и кто уже решал знает ``apps.signoff``, и спрашивается он через
    ``interface`` (к ``ApprovalTask`` доступа нет). Выключенный signoff
    даёт ПУСТЫЕ вкладки, а не 503: список запросов — не согласование, и
    «отправленные» должны открываться, даже когда решать некому.
    """
    qs = RequestInstance.objects.all()
    if box == "sent":
        qs = qs.filter(initiator_id=user_id)
    elif box == "cc":
        qs = qs.filter(pk__in=RequestWatcher.objects.filter(user_id=user_id)
                       .values("request_id"))
    elif box == "done":
        qs = qs.filter(pk__in=_signoff_ids(
            signoff.list_decided_subject_ids, user_id))
    else:
        qs = qs.filter(pk__in=_signoff_ids(
            signoff.list_awaiting_subject_ids, user_id))
    return list(qs.order_by("-created_at"))


def _signoff_ids(query, user_id: int) -> list[int]:
    try:
        return query(user_id, RequestInstance.SIGNOFF_SUBJECT_TYPE)
    except ServiceDisabled:
        return []


@transaction.atomic
def create_instance(data, *, token) -> RequestInstance:
    template = RequestFormTemplate.objects.filter(pk=data.template_id).first()
    if template is None:
        raise Http404("Template not found")
    if template.status != "active":
        raise RuntimeConflict("Форма заблокирована")
    if template.current_version_id is None:
        raise RuntimeConflict("template has no published version")

    initiator_id = token.user_id
    delegated = (data.on_behalf_of is not None
                 and data.on_behalf_of != token.user_id)
    if delegated:
        settings = settings_for_template(template.id)
        # Both conditions, as in the original: the template must opt in AND
        # the actor must be elevated. Either alone is not enough.
        if not settings["allow_delegate_submission"] or not token.is_elevated:
            raise PermissionDenied("delegated submission is not allowed")
        initiator_id = data.on_behalf_of

    instance = RequestInstance.objects.create(
        code=request_runtime.next_code(template),
        template=template,
        template_version_id=template.current_version_id,
        project_id=(data.project_id if data.project_id is not None
                    else template.project_id),
        initiator_id=initiator_id,
        title=data.title,
        form_values_json=_derived(_version_schema(template), data.form_values),
        status=RequestStatus.DRAFT,
    )
    if delegated:
        request_runtime.log(instance, "created_on_behalf", token.user_id,
                            {"for": initiator_id})
    else:
        request_runtime.log(instance, "created", token.user_id, None)

    from .template_data_table import sync_row_for_instance
    sync_row_for_instance(instance)
    instance.refresh_from_db()
    return instance


@transaction.atomic
def update_draft(instance_id: int, data, *, token) -> RequestInstance:
    """Edit a draft or a returned request.

    Правка одобренной заявки «в течение N дней» (``allow_modify_approved``)
    ушла вместе со старым движком: у signoff согласованный документ заперт,
    и единственный ключ — вернуть его на доработку (``reopen``), после чего
    заявка правится как возвращённая и отправляется заново.
    """
    instance = get_or_404(instance_id)
    if instance.initiator_id != token.user_id:
        raise PermissionDenied("only the initiator can edit")

    # Замок согласования — первым: на согласовании и после решения заявка
    # заперта (``Approvable.assert_editable``), и снять замок может только
    # возврат на доработку. 409 с текстом движка — что именно и как отпереть.
    try:
        instance.assert_editable()
    except signoff.SubjectLocked as exc:
        raise RuntimeConflict(str(exc)) from exc
    if instance.status not in (RequestStatus.DRAFT, RequestStatus.RETURNED):
        raise RuntimeConflict("request is not editable in its current state")

    if data.title is not None:
        instance.title = data.title
    if data.form_values is not None:
        instance.form_values_json = _derived(_schema_json(instance), data.form_values)
    instance.save()

    from .template_data_table import sync_row_for_instance
    sync_row_for_instance(instance)
    instance.refresh_from_db()
    return instance


def stage_fillable(instance_id: int, *, token) -> dict:
    """Рабочий шаг этого пользователя по заявке ПРЯМО СЕЙЧАС.

    ``keys`` — поля с ``filled_by = approver``, которых требует его активный
    этап signoff (``requirement_key = field:<key>``): ровно блок текущего
    шага, а не все поля закупщика разом — на шаге «Поиск поставщика» человек
    видит поставщика, а не ещё и счёт, до которого неделя. Не его очередь,
    или его этап ничего от заявки не ждёт (утверждение CFO) — пусто.

    Рядом — чего ещё ждёт этап от РЕШЕНИЯ (``requires_attachment`` /
    ``requires_comment``) и приложенный файл: панель шага показывает всё,
    что нужно, чтобы закрыть его на месте, а проверяет это движок.
    """
    empty = {"keys": [], "required_keys": [], "task_id": None, "stage_name": "",
             "requires_attachment": False, "requires_comment": False,
             "file_id": None, "file_url": None, "file_name": ""}
    instance = get_visible_or_404(instance_id, token=token)
    if instance.status != RequestStatus.PENDING:
        return empty
    try:
        step = signoff.pending_step(
            user_id=token.user_id,
            subject_type=RequestInstance.SIGNOFF_SUBJECT_TYPE,
            subject_id=instance.pk)
    except ServiceDisabled:
        step = None
    if step is None:
        return empty

    from ..approval_hooks import KEY_FIELD_PREFIX
    from .value_validation import approver_fields
    key = step["requirement_key"]
    wanted = key[len(KEY_FIELD_PREFIX):] if key.startswith(KEY_FIELD_PREFIX) else None
    keys = [field.key for field in approver_fields(_schema_json(instance))
            if field.key == wanted]
    return {
        "keys": keys,
        "required_keys": list(keys),
        "task_id": step["task_id"],
        "stage_name": step["stage_name"],
        "requires_attachment": step["requires_attachment"],
        "requires_comment": step["requires_comment"],
        "file_id": step["file_id"],
        # Ссылка и имя — чтобы панель показала приложенное, а не только
        # сообщила, что оно есть.
        "file_url": (step.get("file") or {}).get("url"),
        "file_name": (step.get("file") or {}).get("filename", ""),
    }


def fill_stage_values(instance_id: int, values: dict, *, token) -> RequestInstance:
    """Записать поля согласующего — только разрешённые ``stage_fillable``.

    Чужой ключ — 409 с названием: молча выбросить его значило бы, что
    человек видит «сохранено», а поле пустое. Не его шаг — тоже 409, а не
    403: заявка ему видна, просто заполнять сейчас не его очередь.
    """
    allowed = stage_fillable(instance_id, token=token)
    if not allowed["keys"]:
        raise RuntimeConflict(
            "Сейчас не ваш шаг — заполнять поля заявки может согласующий, "
            "чей этап этого требует")
    foreign = sorted(set(values) - set(allowed["keys"]))
    if foreign:
        raise RuntimeConflict(
            "На вашем шаге нельзя заполнить: " + ", ".join(foreign))

    instance = get_or_404(instance_id)
    merged = _derived(_schema_json(instance),
                      {**(instance.form_values_json or {}), **values})
    # Та же проверка, что при подаче: неизвестных ключей нет, типы в норме.
    from .value_validation import validate_values
    try:
        validate_values(_schema_json(instance), merged)
    except ValueError as exc:
        raise RuntimeConflict(str(exc)) from exc

    instance.form_values_json = merged
    # Итог пересчитываем здесь же: сумма закупа приезжает в блоке
    # согласующего, то есть ПОСЛЕ отправки, а ``total_amount`` считался
    # только на ней — без пересчёта личная аналитика и роллапы видели бы ноль.
    from .value_validation import compute_total
    instance.total_amount = compute_total(_schema_json(instance), merged)
    instance.save(update_fields=["form_values_json", "total_amount", "updated_at"])
    RequestActivity.objects.create(
        request=instance, actor_id=token.user_id,
        event_type="stage_values_filled",
        payload={"keys": sorted(values)})

    from .template_data_table import sync_row_for_instance
    sync_row_for_instance(instance)
    instance.refresh_from_db()
    return instance


def _version_schema(template) -> dict:
    version = RequestFormTemplateVersion.objects.filter(
        pk=template.current_version_id).first()
    return version.schema_json if version else {"fields": []}


def _derived(schema_json: dict, values: dict | None) -> dict:
    """Значения с выведенными полями виджетов.

    Сейчас это только сравнительная таблица поставщиков: её ``total`` и
    ``supplier_name`` считает сервер (``services/quotes.py``), а не клиент —
    по этому числу утверждают деньги и сверяют счёт. Вызывается на КАЖДОМ
    сохранении, и в одном месте: иначе черновик, правка и блок согласующего
    разошлись бы в том, посчитан итог или нет.

    Сломанная схема не должна мешать сохранить черновик — значения тогда
    уходят как есть, а на схему пожалуется публикация и отправка.
    """
    values = values or {}
    try:
        schema = validate_form_schema(schema_json)
    except ValueError:
        return values
    return quotes.derive(schema, values)


def _schema_json(instance: RequestInstance) -> dict:
    version = RequestFormTemplateVersion.objects.filter(
        pk=instance.template_version_id).first()
    return version.schema_json if version else {"fields": []}


def submit(instance_id: int, *, token, resubmit: bool = False) -> dict:
    """Отправить заявку на согласование; вернуть карточку процесса signoff."""
    instance = get_or_404(instance_id)
    verb = "resubmit" if resubmit else "submit"
    if instance.initiator_id != token.user_id:
        raise PermissionDenied(f"only the initiator can {verb}")
    if resubmit and instance.status != RequestStatus.RETURNED:
        raise RuntimeConflict("only a returned request can be resubmitted")
    return request_runtime.submit(instance, actor_id=token.user_id)
