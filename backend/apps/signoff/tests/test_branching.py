"""Условные ветки на настоящем маршруте: движок, снимок, журнал, HTTP.

Чистая логика отбора проверена в ``test_conditions.py`` без БД. Здесь —
то, чего там быть не может: что ветка доезжает до снимка процесса, что
несошедшаяся группа отказывает пользователю понятным 409, что правка
маршрута не переигрывает идущее согласование и что редактор получает
справочник полей от предметной аппки.

Форма маршрута везде одна и та же — та, ради которой всё затевалось:
двое проверяют → ветка по «зоне» → один утверждает.
"""

from __future__ import annotations

import pytest
from django.test import Client

from apps.signoff.models import ApprovalEvent, ApprovalProcess, Quorum
from apps.signoff.services import conditions, engine
from apps.signoff.tests.helpers import (
    BASE,
    SUBJECT,
    admin_token,
    auth,
    make_doc,
    make_route,
    make_user,
    patch_json,
    post_json,
    stage_names,
    token,
    user_token,
)

pytestmark = pytest.mark.django_db


def zone(*values):
    return [{"field": "zone", "op": "in", "value": list(values)}]


@pytest.fixture
def approvers():
    """Разные люди на каждом этапе — иначе не видно, КОГО выбрала ветка."""
    return {name: make_user(name) for name in
            ("checker", "zone1", "zone2", "other", "boss")}


def branching_route(approvers, *, fallback: bool = False):
    stages = [
        (1, "Проверка", Quorum.ALL, [approvers["checker"].pk]),
        (2, "Зона 1", Quorum.ALL, [approvers["zone1"].pk], {"condition": zone(1)}),
        (2, "Зона 2", Quorum.ALL, [approvers["zone2"].pk], {"condition": zone(2)}),
        (3, "Утверждение", Quorum.ALL, [approvers["boss"].pk]),
    ]
    if fallback:
        stages.append((2, "Прочие зоны", Quorum.ALL, [approvers["other"].pk],
                       {"is_fallback": True}))
    return make_route(stages)


# ═══════════════════════════════════════════════════════════════════════
# Снимок процесса
# ═══════════════════════════════════════════════════════════════════════

def test_only_the_matching_branch_enters_the_snapshot(approvers):
    branching_route(approvers)
    doc = make_doc(zone=2)

    process = engine.start(subject_type=SUBJECT, subject_id=doc.pk)

    assert stage_names(process) == ["Проверка", "Зона 2", "Утверждение"]


def test_the_other_branch_gets_no_task(approvers):
    """Не просто «этапа нет в списке» — у чужой ветки не должно появиться и
    запроса, иначе он повиснет в чьём-то «ждёт моего решения»."""
    branching_route(approvers)
    doc = make_doc(zone=2)

    process = engine.start(subject_type=SUBJECT, subject_id=doc.pk)

    addressed = set(process.stages.values_list("tasks__user_id", flat=True))
    assert approvers["zone1"].pk not in addressed
    assert approvers["zone2"].pk in addressed


def test_facts_are_snapshotted_on_the_process(approvers):
    branching_route(approvers)
    doc = make_doc(zone=1, amount=500)

    process = engine.start(subject_type=SUBJECT, subject_id=doc.pk)

    assert process.subject_facts == {"zone": 1, "amount": 500, "urgent": False}


def test_stage_records_how_it_got_in(approvers):
    branching_route(approvers, fallback=True)
    doc = make_doc(zone=3)

    process = engine.start(subject_type=SUBJECT, subject_id=doc.pk)

    by_name = {stage.name: stage for stage in process.stages.all()}
    assert by_name["Проверка"].matched_by == conditions.MATCH_ALWAYS
    assert by_name["Прочие зоны"].matched_by == conditions.MATCH_FALLBACK
    # У сработавшего «иначе» условие пустое ровно как у безусловного этапа —
    # различает их только matched_by, ради чего поле и заведено.
    assert by_name["Прочие зоны"].condition == []


def test_started_event_records_facts_and_the_roads_not_taken(approvers):
    """Карточка процесса показывает только вошедшее. Ответ на «а почему тут
    нет второй зоны» должен остаться хотя бы в журнале."""
    branching_route(approvers)
    doc = make_doc(zone=1)

    process = engine.start(subject_type=SUBJECT, subject_id=doc.pk)

    started = ApprovalEvent.objects.get(process=process, kind="started")
    assert started.payload["facts"]["zone"] == 1
    assert [row["name"] for row in started.payload["skipped_stages"]] == ["Зона 2"]


# ═══════════════════════════════════════════════════════════════════════
# Пустая группа — отказ, а не тихий пропуск
# ═══════════════════════════════════════════════════════════════════════

def test_unmatched_group_refuses_to_start(approvers):
    branching_route(approvers)
    doc = make_doc(zone=3)

    with pytest.raises(engine.RouteUnusable) as exc:
        engine.start(subject_type=SUBJECT, subject_id=doc.pk)

    # В тексте — и шаг, и факты: читать его будет не автор маршрута, а
    # человек, нажавший «отправить».
    assert "нет ветки" in str(exc.value)
    assert "zone=3" in str(exc.value)


def test_nothing_is_written_when_the_group_is_empty(approvers):
    """Отказ обязан быть чистым: полупроцесс без одной группы этапов хуже,
    чем отсутствие процесса."""
    branching_route(approvers)
    doc = make_doc(zone=3)

    with pytest.raises(engine.RouteUnusable):
        engine.start(subject_type=SUBJECT, subject_id=doc.pk)

    assert not ApprovalProcess.objects.filter(subject_id=doc.pk).exists()
    doc.refresh_from_db()
    assert doc.approval_state == "draft"


def test_fallback_rescues_the_unmatched_group(approvers):
    branching_route(approvers, fallback=True)
    doc = make_doc(zone=3)

    process = engine.start(subject_type=SUBJECT, subject_id=doc.pk)

    assert stage_names(process) == ["Проверка", "Прочие зоны", "Утверждение"]


def test_route_referencing_an_unknown_fact_refuses_to_start(approvers):
    """Маршрут разошёлся с тем, что аппка отдаёт в facts (ключ переименовали).
    Молча считать условие ложным — значит потерять этап."""
    make_route([
        (1, "Проверка", Quorum.ALL, [approvers["checker"].pk]),
        (2, "Ветка", Quorum.ALL, [approvers["zone1"].pk],
         {"condition": [{"field": "страна", "op": "eq", "value": 1}]}),
    ])
    doc = make_doc(zone=1)

    with pytest.raises(engine.RouteUnusable, match="настроен неверно"):
        engine.start(subject_type=SUBJECT, subject_id=doc.pk)


def test_inactive_approver_in_an_unrelated_branch_does_not_block(approvers):
    """Уволившийся согласующий мешает запуску только если он на ЭТОМ пути.

    Иначе одна протухшая ветка останавливала бы согласование всех остальных
    зон — и чинить её пришлось бы срочно, вместо того чтобы починить к сроку.
    """
    quitter = make_user("quitter", active=False)
    make_route([
        (1, "Зона 1", Quorum.ALL, [approvers["zone1"].pk], {"condition": zone(1)}),
        (1, "Зона 2", Quorum.ALL, [quitter.pk], {"condition": zone(2)}),
    ])

    process = engine.start(subject_type=SUBJECT, subject_id=make_doc(zone=1).pk)
    assert stage_names(process) == ["Зона 1"]

    with pytest.raises(engine.RouteUnusable, match="не осталось ни одного активного"):
        engine.start(subject_type=SUBJECT, subject_id=make_doc(zone=2).pk)


# ═══════════════════════════════════════════════════════════════════════
# Снимок неизменен
# ═══════════════════════════════════════════════════════════════════════

def test_editing_the_route_does_not_reshuffle_a_running_process(approvers):
    route = branching_route(approvers)
    doc = make_doc(zone=1)
    process = engine.start(subject_type=SUBJECT, subject_id=doc.pk)

    # Администратор переписал ветки — идущее согласование это не касается.
    route.stages.filter(name="Зона 1").update(condition=zone(2))
    route.stages.filter(name="Зона 2").update(condition=zone(1))

    process.refresh_from_db()
    assert stage_names(process) == ["Проверка", "Зона 1", "Утверждение"]


def test_changing_the_subject_does_not_reshuffle_a_running_process(approvers):
    """Ветки считаются один раз, на запуске — ровно как и всё остальное в
    снимке. Иначе правка объекта посреди согласования меняла бы состав
    согласующих задним числом."""
    branching_route(approvers)
    doc = make_doc(zone=1)
    process = engine.start(subject_type=SUBJECT, subject_id=doc.pk)

    doc.zone = 2
    doc.save(update_fields=["zone"])

    process.refresh_from_db()
    assert stage_names(process) == ["Проверка", "Зона 1", "Утверждение"]
    assert process.subject_facts["zone"] == 1


# ═══════════════════════════════════════════════════════════════════════
# Обратная совместимость
# ═══════════════════════════════════════════════════════════════════════

def test_route_without_conditions_behaves_exactly_as_before(approvers):
    make_route([
        (1, "Первый", Quorum.ALL, [approvers["checker"].pk]),
        (2, "Второй", Quorum.ALL, [approvers["boss"].pk]),
    ])

    process = engine.start(subject_type=SUBJECT, subject_id=make_doc().pk)

    assert stage_names(process) == ["Первый", "Второй"]
    assert all(stage.matched_by == conditions.MATCH_ALWAYS
               for stage in process.stages.all())


# ═══════════════════════════════════════════════════════════════════════
# HTTP
# ═══════════════════════════════════════════════════════════════════════

def test_subjects_endpoint_carries_the_fields_of_the_domain_app():
    """Откуда редактор узнаёт, что у документа бывает «зона» и какие зоны
    существуют: signoff этого не знает, он передаёт сказанное аппкой."""
    client = Client()
    response = client.get(f"{BASE}/subjects", **auth(token()))
    assert response.status_code == 200

    probe = next(row for row in response.json() if row["subject_type"] == SUBJECT)
    zone_field = next(f for f in probe["fields"] if f["key"] == "zone")
    assert zone_field["type"] == "choice"
    assert zone_field["label"] == "Зона"
    assert [option["value"] for option in zone_field["options"]] == [1, 2, 3]


def test_stage_can_be_created_with_a_condition(approvers):
    route = make_route([(1, "Проверка", Quorum.ALL, [approvers["checker"].pk])])
    client = Client()

    response = post_json(client, f"{BASE}/routes/{route.pk}/stages", {
        "order": 2, "name": "Зона 1", "quorum": "all",
        "approver_ids": [approvers["zone1"].pk], "condition": zone(1),
    }, **auth(admin_token()))

    assert response.status_code == 201, response.content
    assert response.json()["condition"] == zone(1)


def test_condition_on_an_unknown_field_is_refused_at_configuration_time(approvers):
    """Опечатку ловим у того, кто настраивает, а не через месяц у того, кто
    отправляет заявку."""
    route = make_route([(1, "Проверка", Quorum.ALL, [approvers["checker"].pk])])
    client = Client()

    response = post_json(client, f"{BASE}/routes/{route.pk}/stages", {
        "order": 2, "name": "Ветка", "quorum": "all",
        "approver_ids": [approvers["zone1"].pk],
        "condition": [{"field": "страна", "op": "eq", "value": 1}],
    }, **auth(admin_token()))

    assert response.status_code == 409
    assert "Неизвестное поле" in response.json()["detail"]


def test_condition_value_outside_the_reference_book_is_refused(approvers):
    route = make_route([(1, "Проверка", Quorum.ALL, [approvers["checker"].pk])])
    client = Client()

    response = post_json(client, f"{BASE}/routes/{route.pk}/stages", {
        "order": 2, "name": "Ветка", "quorum": "all",
        "approver_ids": [approvers["zone1"].pk], "condition": zone(99),
    }, **auth(admin_token()))

    assert response.status_code == 409
    assert "неизвестные значения" in response.json()["detail"]


def test_fallback_with_its_own_condition_is_refused(approvers):
    route = make_route([(1, "Проверка", Quorum.ALL, [approvers["checker"].pk])])
    client = Client()

    response = post_json(client, f"{BASE}/routes/{route.pk}/stages", {
        "order": 2, "name": "Ветка", "quorum": "all",
        "approver_ids": [approvers["zone1"].pk],
        "condition": zone(1), "is_fallback": True,
    }, **auth(admin_token()))

    assert response.status_code == 409
    assert "не может иметь собственного условия" in response.json()["detail"]


def test_unknown_operator_is_a_422(approvers):
    """Форму запроса ловит схема, а не сервис."""
    route = make_route([(1, "Проверка", Quorum.ALL, [approvers["checker"].pk])])
    client = Client()

    response = post_json(client, f"{BASE}/routes/{route.pk}/stages", {
        "order": 2, "name": "Ветка", "quorum": "all",
        "approver_ids": [approvers["zone1"].pk],
        "condition": [{"field": "zone", "op": "магия", "value": 1}],
    }, **auth(admin_token()))

    assert response.status_code == 422


def test_condition_can_be_cleared_by_patch(approvers):
    route = branching_route(approvers)
    stage = route.stages.get(name="Зона 1")
    client = Client()

    response = patch_json(client, f"{BASE}/stages/{stage.pk}", {"condition": []},
                          **auth(admin_token()))

    assert response.status_code == 200, response.content
    assert response.json()["condition"] == []
    stage.refresh_from_db()
    assert stage.condition == []


def test_patch_without_condition_leaves_it_alone(approvers):
    """``None`` в PATCH-схеме значит «не трогать», пустой список — «снять».
    Различает их exclude_unset, и это стоит проверить отдельно: перепутать
    их значило бы стирать ветку при переименовании этапа."""
    route = branching_route(approvers)
    stage = route.stages.get(name="Зона 1")
    client = Client()

    response = patch_json(client, f"{BASE}/stages/{stage.pk}",
                          {"name": "Зона один"}, **auth(admin_token()))

    assert response.status_code == 200, response.content
    stage.refresh_from_db()
    assert stage.name == "Зона один"
    assert stage.condition == zone(1)


def test_route_card_warns_about_options_without_a_branch(approvers):
    """Дыру в покрытии администратор должен увидеть в редакторе, а не
    получить рикошетом от пользователя через месяц."""
    route = branching_route(approvers)
    client = Client()

    response = client.get(f"{BASE}/routes/{route.pk}", **auth(admin_token()))

    assert response.status_code == 200
    gaps = response.json()["coverage_gaps"]
    assert len(gaps) == 1
    assert gaps[0]["order"] == 2
    assert gaps[0]["label"] == "Зона"
    assert [option["value"] for option in gaps[0]["missing"]] == [3]


def test_no_warning_once_a_fallback_closes_the_group(approvers):
    route = branching_route(approvers, fallback=True)
    client = Client()

    response = client.get(f"{BASE}/routes/{route.pk}", **auth(admin_token()))

    assert response.json()["coverage_gaps"] == []


def test_process_card_shows_the_facts_and_the_branch(approvers):
    branching_route(approvers)
    doc = make_doc(zone=2)
    process = engine.start(subject_type=SUBJECT, subject_id=doc.pk)
    client = Client()

    response = client.get(
        f"{BASE}/processes/{process.pk}",
        **auth(user_token(approvers["checker"])),
    )

    assert response.status_code == 200
    card = response.json()
    assert card["subject_facts"]["zone"] == 2
    branch = next(stage for stage in card["stages"] if stage["name"] == "Зона 2")
    assert branch["matched_by"] == "condition"
    assert branch["condition"] == zone(2)


def test_submitting_an_uncovered_subject_answers_409(approvers):
    """Сквозная проверка того, ради чего ошибка вообще носит текст: отказ
    доезжает до пользователя как 409 с объяснением, а не как 500."""
    branching_route(approvers)
    doc = make_doc(zone=3)
    client = Client()

    response = post_json(client, f"{BASE}/processes", {
        "subject_type": SUBJECT, "subject_id": doc.pk,
    }, **auth(admin_token()))

    assert response.status_code == 409
    assert "нет ветки" in response.json()["detail"]
