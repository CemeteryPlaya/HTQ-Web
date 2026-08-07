"""Этап подписи: согласует инициатор, и только с приложенным документом.

Две независимые вещи, проверяются раздельно и в паре:

* ``ApproverKind.INITIATOR`` — согласующий, которого в маршруте нет: он
  вычисляется на запуске из ``ApprovalProcess.initiator_id``;
* ``requires_attachment`` — этап, который нельзя согласовать без файла.

Хранилище подменяется (``stub_storage``): здесь проверяются права, гейт и
запись ``file_id``, а не работоспособность MinIO — за неё отвечают тесты
media_files. Тот же приём, что в
``apps/contracts/tests/test_agreements_api.py::stub_storage``.
"""

from __future__ import annotations

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.signoff.models import (
    ApprovalEvent,
    ApprovalTask,
    ApproverKind,
    ProcessState,
    Quorum,
    StageState,
    TaskState,
)
from apps.signoff.services import attachments, engine
from apps.signoff.services import route_service as routes
from apps.signoff.tests.helpers import (
    BASE,
    admin_token,
    auth,
    make_doc,
    make_route,
    make_user,
    patch_json,
    post_json,
    task_for,
    token,
    user_token,
)
from apps.signoff.tests.testapp import hooks
from apps.signoff.tests.testapp.models import ProbeDoc

pytestmark = pytest.mark.django_db

SUBJECT = ProbeDoc.SIGNOFF_SUBJECT_TYPE

SIGNATURE = {"approver_kind": ApproverKind.INITIATOR, "requires_attachment": True}


@pytest.fixture(autouse=True)
def _reset_calls():
    hooks.reset()
    yield
    hooks.reset()


@pytest.fixture
def stub_storage(monkeypatch):
    """``store_file`` отдаёт готовый id, не ходя в MinIO."""
    calls = []

    def fake(**kwargs):
        calls.append(kwargs)
        return {"id": f"stored-{len(calls)}"}

    monkeypatch.setattr("apps.signoff.services.attachments.media.store_file", fake)
    # Ссылку тоже не строим: подписывать нечего, файла в хранилище нет.
    monkeypatch.setattr("apps.signoff.services.attachments.media.get_file_url",
                        lambda file_id, *a, **kw: f"https://files.test/{file_id}")
    return calls


def _signature_route(*named_ids: int):
    """Обычный этап + этап подписи инициатора последним."""
    return make_route([
        (1, "Проверка", Quorum.ALL, list(named_ids)),
        (2, "Подпись инициатора", Quorum.ALL, [], SIGNATURE),
    ])


def _attach(client, task_id: int, tok: str, *, name="doc.pdf",
            content=b"%PDF-1.4", mime="application/pdf"):
    return client.post(f"{BASE}/tasks/{task_id}/attachment",
                       {"file": SimpleUploadedFile(name, content, mime)},
                       **auth(tok))


def _decide(client, task_id: int, tok: str, decision="approve", comment=""):
    return post_json(client, f"{BASE}/tasks/{task_id}/decision",
                     {"decision": decision, "comment": comment}, **auth(tok))


# ═══════════════════════════════════════════════════════════════════════
# Кто согласует этап подписи
# ═══════════════════════════════════════════════════════════════════════

def test_an_initiator_stage_addresses_its_task_to_the_initiator():
    """Согласующего в маршруте нет — он берётся из процесса на запуске."""
    checker, author = make_user("checker"), make_user("author")
    doc = make_doc()
    _signature_route(checker.pk)

    process = engine.start(subject_type=SUBJECT, subject_id=doc.pk,
                           initiator_id=author.pk)

    signature = process.stages.get(order=2)
    assert signature.approver_kind == ApproverKind.INITIATOR
    assert list(signature.tasks.values_list("user_id", flat=True)) == [author.pk]


def test_a_process_without_an_initiator_cannot_use_a_signature_stage():
    """Операторский запуск без ``initiator_id``: подписывать некому, и
    отказать надо на запуске, а не оставить этап без задач."""
    checker = make_user("checker")
    doc = make_doc()
    _signature_route(checker.pk)

    with pytest.raises(engine.RouteUnusable, match="без инициатора"):
        engine.start(subject_type=SUBJECT, subject_id=doc.pk, initiator_id=None)


def test_a_deactivated_initiator_is_reported_as_such_not_as_a_broken_route():
    """Маршрут тут ни при чём — «поправьте маршрут» отправило бы человека
    не туда."""
    checker = make_user("checker")
    fired = make_user("fired", active=False)
    doc = make_doc()
    _signature_route(checker.pk)

    with pytest.raises(engine.RouteUnusable, match="учётная запись неактивна"):
        engine.start(subject_type=SUBJECT, subject_id=doc.pk,
                     initiator_id=fired.pk)


def test_the_initiator_signs_last_and_that_finishes_the_process(client, stub_storage):
    """Полный проход: проверяющий согласовал, подпись открылась, инициатор
    приложил документ и подписал — процесс согласован."""
    checker, author = make_user("checker"), make_user("author")
    doc = make_doc()
    _signature_route(checker.pk)
    process = engine.start(subject_type=SUBJECT, subject_id=doc.pk,
                           initiator_id=author.pk)

    engine.act(task_id=task_for(process, checker.pk).pk, actor_id=checker.pk,
               decision="approve")
    process.refresh_from_db()
    assert process.current_order == 2

    signature_task = task_for(process, author.pk)
    assert _attach(client, signature_task.pk, user_token(author)).status_code == 200
    decided = _decide(client, signature_task.pk, user_token(author))

    assert decided.status_code == 200, decided.content
    assert decided.json()["state"] == ProcessState.APPROVED
    doc.refresh_from_db()
    assert doc.published is True


def test_named_approvers_on_an_initiator_stage_are_not_consulted():
    """Сочетание запрещено настройкой, но данные могут прийти из админки —
    движок берёт инициатора и только его, а не объединяет списки."""
    named, author = make_user("named"), make_user("author")
    doc = make_doc()
    make_route([(1, "Подпись", Quorum.ALL, [named.pk], SIGNATURE)])

    process = engine.start(subject_type=SUBJECT, subject_id=doc.pk,
                           initiator_id=author.pk)

    assert list(ApprovalTask.objects.filter(stage__process=process)
                .values_list("user_id", flat=True)) == [author.pk]


# ═══════════════════════════════════════════════════════════════════════
# Гейт документа
# ═══════════════════════════════════════════════════════════════════════

def test_approving_without_a_document_is_refused():
    author = make_user("author")
    doc = make_doc()
    make_route([(1, "Подпись", Quorum.ALL, [], SIGNATURE)])
    process = engine.start(subject_type=SUBJECT, subject_id=doc.pk,
                           initiator_id=author.pk)
    task = task_for(process, author.pk)

    with pytest.raises(engine.AttachmentRequired, match="приложенным документом"):
        engine.act(task_id=task.pk, actor_id=author.pk, decision="approve")

    # Отказ по гейту не оставляет за собой закрытую задачу.
    task.refresh_from_db()
    assert task.state == TaskState.PENDING
    process.refresh_from_db()
    assert process.state == ProcessState.PENDING


def test_rejecting_without_a_document_is_allowed():
    """Требовать PDF от того, кто отклоняет, незачем: документа, который ему
    полагалось бы подписать, не существует."""
    author = make_user("author")
    doc = make_doc()
    make_route([(1, "Подпись", Quorum.ALL, [], SIGNATURE)])
    process = engine.start(subject_type=SUBJECT, subject_id=doc.pk,
                           initiator_id=author.pk)

    engine.act(task_id=task_for(process, author.pk).pk, actor_id=author.pk,
               decision="reject", comment="передумал")

    process.refresh_from_db()
    assert process.state == ProcessState.REJECTED


def test_the_document_requirement_comes_from_the_snapshot_not_the_route():
    """Снять галочку в маршруте посреди согласования не должно избавлять от
    документа тех, кто ещё не решил."""
    author = make_user("author")
    doc = make_doc()
    route = make_route([(1, "Подпись", Quorum.ALL, [], SIGNATURE)])
    process = engine.start(subject_type=SUBJECT, subject_id=doc.pk,
                           initiator_id=author.pk)

    route.stages.update(requires_attachment=False)

    with pytest.raises(engine.AttachmentRequired):
        engine.act(task_id=task_for(process, author.pk).pk, actor_id=author.pk,
                   decision="approve")


def test_the_signed_document_lands_in_the_journal(client, stub_storage):
    """«На основании чего согласовано» — вопрос к журналу, и искать ответ в
    другом месте не должно быть нужно."""
    author = make_user("author")
    doc = make_doc()
    make_route([(1, "Подпись", Quorum.ALL, [], SIGNATURE)])
    process = engine.start(subject_type=SUBJECT, subject_id=doc.pk,
                           initiator_id=author.pk)
    task = task_for(process, author.pk)

    _attach(client, task.pk, user_token(author))
    _decide(client, task.pk, user_token(author))

    attached = ApprovalEvent.objects.get(process=process, kind="task_file_attached")
    assert attached.payload["file_id"] == "stored-1"
    assert attached.payload["filename"] == "doc.pdf"
    approved = ApprovalEvent.objects.get(process=process, kind="task_approved")
    assert approved.payload["file_id"] == "stored-1"


# ═══════════════════════════════════════════════════════════════════════
# Загрузка документа
# ═══════════════════════════════════════════════════════════════════════

def test_only_the_addressee_attaches_the_document(client, stub_storage):
    """Администраторского исключения здесь нет намеренно: загрузка файла за
    согласующего была бы подделкой подписи."""
    author, stranger = make_user("author"), make_user("stranger")
    doc = make_doc()
    make_route([(1, "Подпись", Quorum.ALL, [], SIGNATURE)])
    process = engine.start(subject_type=SUBJECT, subject_id=doc.pk,
                           initiator_id=author.pk)
    task = task_for(process, author.pk)

    assert _attach(client, task.pk, user_token(stranger)).status_code == 409
    assert _attach(client, task.pk, admin_token()).status_code == 409
    assert _attach(client, task.pk, user_token(author)).status_code == 200


def test_a_stage_that_does_not_ask_for_a_document_refuses_one(client, stub_storage):
    a = make_user("a")
    doc = make_doc()
    make_route([(1, "Обычный этап", Quorum.ALL, [a.pk])])
    process = engine.start(subject_type=SUBJECT, subject_id=doc.pk,
                           initiator_id=a.pk)

    refused = _attach(client, task_for(process, a.pk).pk, user_token(a))
    assert refused.status_code == 409
    assert "документ не требуется" in refused.json()["detail"]


def test_a_document_cannot_be_attached_before_the_stage_is_reached(client, stub_storage):
    checker, author = make_user("checker"), make_user("author")
    doc = make_doc()
    _signature_route(checker.pk)
    process = engine.start(subject_type=SUBJECT, subject_id=doc.pk,
                           initiator_id=author.pk)

    assert process.stages.get(order=2).state == StageState.WAITING
    refused = _attach(client, task_for(process, author.pk).pk, user_token(author))
    assert refused.status_code == 409
    assert "очередь до него не дошла" in refused.json()["detail"]


def test_a_second_upload_replaces_the_first_and_says_so(client, stub_storage):
    """Человек вправе загрузить не тот файл и исправиться, пока не решил."""
    author = make_user("author")
    doc = make_doc()
    make_route([(1, "Подпись", Quorum.ALL, [], SIGNATURE)])
    process = engine.start(subject_type=SUBJECT, subject_id=doc.pk,
                           initiator_id=author.pk)
    task = task_for(process, author.pk)

    _attach(client, task.pk, user_token(author), name="wrong.pdf")
    second = _attach(client, task.pk, user_token(author), name="right.pdf")

    assert second.json()["file_id"] == "stored-2"
    replaced = ApprovalEvent.objects.filter(
        process=process, kind="task_file_attached").last()
    assert replaced.payload["replaced_file_id"] == "stored-1"


def test_a_missing_file_field_is_422(client, stub_storage):
    author = make_user("author")
    doc = make_doc()
    make_route([(1, "Подпись", Quorum.ALL, [], SIGNATURE)])
    process = engine.start(subject_type=SUBJECT, subject_id=doc.pk,
                           initiator_id=author.pk)

    empty = client.post(f"{BASE}/tasks/{task_for(process, author.pk).pk}/attachment",
                        {}, **auth(user_token(author)))
    assert empty.status_code == 422


def test_a_rejection_from_the_upload_pipeline_keeps_its_status(client, monkeypatch):
    """415 «это не PDF» и 413 «слишком большой» — разные причины, и сводить
    их к общему 400 значило бы спрятать от пользователя единственное, что
    ему надо исправить. Сам PDF-only задан политикой scope в media_files."""
    author = make_user("author")
    doc = make_doc()
    make_route([(1, "Подпись", Quorum.ALL, [], SIGNATURE)])
    process = engine.start(subject_type=SUBJECT, subject_id=doc.pk,
                           initiator_id=author.pk)

    def reject(**kwargs):
        error = ValueError("Mime 'image/png' not allowed for scope 'signoff_doc'")
        error.status_code = 415
        error.detail = str(error)
        raise error

    monkeypatch.setattr("apps.signoff.services.attachments.media.store_file", reject)

    refused = _attach(client, task_for(process, author.pk).pk, user_token(author),
                      name="scan.png", content=b"\x89PNG", mime="image/png")
    assert refused.status_code == 415
    assert "signoff_doc" in refused.json()["detail"]


def test_the_process_card_shows_the_attached_document(client, stub_storage):
    author = make_user("author")
    doc = make_doc()
    make_route([(1, "Подпись", Quorum.ALL, [], SIGNATURE)])
    process = engine.start(subject_type=SUBJECT, subject_id=doc.pk,
                           initiator_id=author.pk)
    task = task_for(process, author.pk)
    _attach(client, task.pk, user_token(author))

    card = client.get(
        f"{BASE}/processes/{process.pk}", **auth(user_token(author)),
    ).json()
    stage = card["stages"][0]
    assert stage["approver_kind"] == ApproverKind.INITIATOR
    assert stage["requires_attachment"] is True
    assert stage["tasks"][0]["file_id"] == "stored-1"
    assert stage["tasks"][0]["file_url"] == "https://files.test/stored-1"


def test_the_inbox_warns_that_a_document_will_be_needed(client, stub_storage):
    """Чтобы человек узнал об этом в очереди, а не упёрся в отказ, уже
    нажав «согласовать»."""
    author = make_user("author")
    doc = make_doc()
    make_route([(1, "Подпись", Quorum.ALL, [], SIGNATURE)])
    engine.start(subject_type=SUBJECT, subject_id=doc.pk, initiator_id=author.pk)

    inbox = client.get(f"{BASE}/tasks/mine", **auth(user_token(author))).json()
    assert inbox[0]["requires_attachment"] is True
    assert inbox[0]["file_id"] is None


def test_deciding_without_the_document_is_409_over_http(client, stub_storage):
    author = make_user("author")
    doc = make_doc()
    make_route([(1, "Подпись", Quorum.ALL, [], SIGNATURE)])
    process = engine.start(subject_type=SUBJECT, subject_id=doc.pk,
                           initiator_id=author.pk)

    refused = _decide(client, task_for(process, author.pk).pk, user_token(author))
    assert refused.status_code == 409
    assert "загрузите PDF" in refused.json()["detail"]


# ═══════════════════════════════════════════════════════════════════════
# Настройка маршрута
# ═══════════════════════════════════════════════════════════════════════

def test_a_signature_stage_is_created_without_approvers(client):
    a = make_user("a")
    route = make_route([(1, "Проверка", Quorum.ALL, [a.pk])])

    created = post_json(client, f"{BASE}/routes/{route.pk}/stages", {
        "order": 2, "name": "Подпись", "approver_ids": [],
        "approver_kind": ApproverKind.INITIATOR, "requires_attachment": True,
    }, **auth(admin_token()))

    assert created.status_code == 201, created.content
    body = created.json()
    assert body["approvers"] == []
    assert body["requires_attachment"] is True


def test_a_signature_stage_with_named_approvers_is_refused(client):
    a = make_user("a")
    route = make_route([(1, "Проверка", Quorum.ALL, [a.pk])])

    refused = post_json(client, f"{BASE}/routes/{route.pk}/stages", {
        "order": 2, "name": "Подпись", "approver_ids": [a.pk],
        "approver_kind": ApproverKind.INITIATOR,
    }, **auth(admin_token()))

    assert refused.status_code == 422, refused.content


def test_switching_a_stage_to_the_initiator_clears_its_approvers(client):
    """Оставшийся список движок игнорировал бы, а редактор больше не
    показывает — значит его надо стереть, а не хранить втихую."""
    a = make_user("a")
    route = make_route([(1, "Проверка", Quorum.ALL, [a.pk]),
                        (2, "Второй", Quorum.ALL, [a.pk])])
    stage = route.stages.get(order=2)

    patched = patch_json(client, f"{BASE}/stages/{stage.pk}",
                         {"approver_kind": ApproverKind.INITIATOR},
                         **auth(admin_token()))

    assert patched.status_code == 200, patched.content
    assert patched.json()["approvers"] == []
    assert not stage.approvers.exists()


def test_switching_back_to_named_without_a_list_is_refused(client):
    a = make_user("a")
    route = make_route([(1, "Проверка", Quorum.ALL, [a.pk]),
                        (2, "Подпись", Quorum.ALL, [], SIGNATURE)])
    stage = route.stages.get(order=2)

    refused = patch_json(client, f"{BASE}/stages/{stage.pk}",
                         {"approver_kind": ApproverKind.NAMED},
                         **auth(admin_token()))

    assert refused.status_code == 409
    assert "хотя бы один согласующий" in refused.json()["detail"]


def test_a_signature_stage_that_is_not_last_is_flagged_in_the_editor(client):
    """Предупреждение, а не запрет: запрет означал бы, что после подписи в
    маршрут нельзя добавить ни одного этапа."""
    a = make_user("a")
    route = make_route([(1, "Подпись", Quorum.ALL, [], SIGNATURE),
                        (2, "И ещё этап", Quorum.ALL, [a.pk])])

    assert routes.initiator_stage_not_last(route) is True
    card = client.get(f"{BASE}/routes/{route.pk}", **auth(admin_token())).json()
    assert card["initiator_stage_not_last"] is True


def test_a_signature_stage_placed_last_is_not_flagged(client):
    a = make_user("a")
    route = _signature_route(a.pk)

    assert routes.initiator_stage_not_last(route) is False
    card = client.get(f"{BASE}/routes/{route.pk}", **auth(admin_token())).json()
    assert card["initiator_stage_not_last"] is False


def test_enums_expose_the_approver_kinds(client):
    """Подписи идут с бэкенда, чтобы фронтовый словарь не разошёлся с
    моделью при первой же правке."""
    enums = client.get(f"{BASE}/enums", **auth(token())).json()
    assert {"value": "initiator", "label": "Инициатор согласования"} in \
        enums["approver_kind"]


# ═══════════════════════════════════════════════════════════════════════
# Ссылка на документ
# ═══════════════════════════════════════════════════════════════════════

def test_a_broken_media_does_not_break_the_process_card(monkeypatch):
    """Выключенный media — причина не показать ССЫЛКУ, но не причина
    отказать в чтении согласования."""
    def boom(*args, **kwargs):
        raise RuntimeError("media упал")

    monkeypatch.setattr("apps.signoff.services.attachments.media.get_file_url", boom)
    assert attachments.file_url("stored-1") is None
