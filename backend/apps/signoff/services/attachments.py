"""Документ, приложенный к решению согласующего.

Отдельно от ``engine.py`` намеренно: там переходы процесса под блокировкой,
здесь — загрузка файла в чужое хранилище. Смешивать их нельзя по той же
причине, по которой уведомления вынесены в ``on_commit``: обращение к S3
внутри транзакции, держащей ``SELECT … FOR UPDATE`` на процессе, заперло бы
согласование на время сетевой операции.

Отсюда и разделение на два запроса. Сначала ``POST /tasks/{id}/attachment``
кладёт файл и запоминает его на задаче, потом ``POST /tasks/{id}/decision``
принимает решение и уже под блокировкой проверяет, что документ на месте
(``engine.act`` → ``AttachmentRequired``). Обратный порядок — «решение с
файлом одним multipart-запросом» — потребовал бы либо загрузки внутри
транзакции, либо отката коммита при неудачной загрузке.

**Кто вправе приложить.** Только тот, кому адресован запрос. Администратору
исключения нет — в отличие от скана договора (``contracts``:
``AgreementFileView``, где админ правит карточку объекта). Здесь файл — часть
персонального решения: «документ, который подписал ЭТОТ человек». Загрузка
администратором за согласующего была бы подделкой подписи, а не
администрированием.

**Про PDF.** Проверяет не signoff, а политика scope в media_files
(``signoff_doc``): она же включает проверку magic-байтов, поэтому
переименованный в ``.pdf`` файл не пройдёт. Дублировать это здесь значило бы
завести второе место, где написано, что документ бывает только PDF.
"""

from __future__ import annotations

import logging

from django.http import Http404

from apps.core.services import ServiceDisabled, require_service
from apps.signoff.models import (
    ApprovalEvent,
    ApprovalTask,
    ProcessState,
    StageState,
    TaskState,
)
from apps.signoff.services.engine import NotAnApprover, ProcessClosed, SignoffError
# Сосед — только через interface (apps/core/tests/test_app_isolation.py).
from apps.media_files import interface as media

logger = logging.getLogger(__name__)

SCOPE = "signoff_doc"


class AttachmentNotExpected(SignoffError):
    """Этап не требует документа — прикладывать некуда.

    Строго, а не «пусть лежит, вдруг пригодится»: галочка «требуется
    документ» на этапе — единственное, из чего интерфейс узнаёт, что тут
    бывает файл. Разрешив загрузку на любой этап, мы получили бы вложения,
    которых никто не показывает, и PDF-only там, где его никто не просил.
    """


class AttachmentRejected(Exception):
    """Пайплайн загрузки media_files отверг файл — оборачивает
    ``UploadValidationError``-совместимый ``ValueError`` соседней аппки
    (status_code/detail) БЕЗ прямого импорта её класса (тот же приём, что
    apps/mail/services/attachment_service.py::AttachmentUploadRejected и
    apps/hr/.../UploadRejected — прямой импорт чего-либо, кроме
    ``apps.media_files.interface``, ловится
    apps/core/tests/test_app_isolation.py)."""

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


def attach(task_id: int, *, actor_id: int, data: bytes, filename: str,
           mime: str) -> ApprovalTask:
    """Приложить документ к своему открытому запросу.

    Повторная загрузка ЗАМЕЩАЕТ ссылку, пока решение не принято: человек
    вправе загрузить не тот файл и исправиться. Старый объект остаётся в
    хранилище — удалять его отсюда нельзя (та же причина, что в
    ``contracts.agreement_service.attach_file``: тихая потеря подписанного
    документа хуже лишнего объекта в S3).

    Блокировки процесса здесь нет и не нужно: функция не делает переходов и
    читает состояние только чтобы отказать заведомо бессмысленной загрузке.
    Худшее, что даёт гонка с ``engine.act`` — файл, записанный на уже
    закрытую задачу (ни на что не влияет), или решение, отклонённое с «нужен
    документ» на файле, который закоммитился мгновением позже (повторная
    попытка проходит).
    """
    require_service("signoff")

    task = (ApprovalTask.objects
            .select_related("stage", "stage__process")
            .filter(pk=task_id).first())
    if task is None:
        raise Http404("Запрос на согласование не найден")
    if task.user_id != actor_id:
        # 409, а не 403 — ровно по тем же соображениям, что в ``engine.act``.
        raise NotAnApprover("Этот запрос адресован другому согласующему")

    stage = task.stage
    if not stage.requires_attachment:
        raise AttachmentNotExpected(
            f"На этапе «{stage.name}» документ не требуется")
    if stage.process.state != ProcessState.PENDING:
        raise ProcessClosed(
            f"Согласование уже завершено "
            f"({stage.process.get_state_display()})")
    if task.state != TaskState.PENDING:
        raise ProcessClosed("По этому запросу решение уже принято")
    if stage.state != StageState.ACTIVE:
        raise ProcessClosed(
            f"Этап «{stage.name}» ещё не на рассмотрении — очередь до него "
            f"не дошла")

    try:
        stored = media.store_file(data=data, filename=filename, mime=mime,
                                  scope=SCOPE, owner_id=actor_id)
    except ValueError as exc:
        status_code = getattr(exc, "status_code", 400)
        detail = getattr(exc, "detail", str(exc))
        raise AttachmentRejected(status_code, detail) from exc

    replaced = task.file_id
    task.file_id = str(stored["id"])
    task.save(update_fields=["file_id"])

    # Журнал ведём и здесь, а не только на решении: загрузка — действие
    # человека, и «приложил один файл, потом другой» должно быть видно.
    # Пишется напрямую, а не через ``engine._log``: это не переход процесса.
    ApprovalEvent.objects.create(
        process_id=stage.process_id, kind="task_file_attached",
        actor_id=actor_id,
        payload={"stage": stage.name, "task_id": task.pk,
                 "file_id": task.file_id, "replaced_file_id": replaced or None,
                 "filename": filename},
    )
    return task


def file_url(file_id: str | None) -> str | None:
    """Подписанная ссылка на приложенный документ (scope приватный).

    Ошибки соседа проглатываются, а карточка процесса всё равно строится:
    выключенный или сломанный media — причина не показать ССЫЛКУ, но не
    причина отдать 503 на чтение согласования, в котором помимо файла есть
    решения, комментарии и журнал. Тот же размен, что у ``describe()`` в
    ``presentation.describe_many``.
    """
    if not file_id:
        return None
    try:
        return media.get_file_url(file_id)
    except ServiceDisabled:
        logger.info("signoff: media выключен, ссылка на документ не построена")
        return None
    except Exception:
        logger.warning("signoff: не удалось построить ссылку на файл %s",
                       file_id, exc_info=True)
        return None
