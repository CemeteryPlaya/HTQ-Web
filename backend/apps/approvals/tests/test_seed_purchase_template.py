"""Команда, заводящая шаблон «Заявка на закуп».

Проверяется то, ради чего команда существует: форма собрана с ПРАВИЛЬНЫМИ
типами (строка бюджета — виджет, единицы — список), повторный запуск ничего
не дублирует, а поданная по шаблону заявка проходит согласование целиком.
"""

import json
from io import StringIO

import pytest
from django.core.management import call_command
from django.test import Client

from apps.approvals.models import (
    RequestFormTemplate, RequestFormTemplateVersion, RequestStatus,
)
from apps.approvals.management.commands.seed_purchase_request_template import (
    BUYER_STAGES, DEFAULT_SLUG, STAGE_CFO, UNITS,
)
from apps.contracts.tests.helpers import make_line
from apps.hr.models import Department, Employee, EmployeeStatus, Position
from apps.signoff.models import ApprovalRoute, ApproverKind
from apps.users.models import User

from .helpers import (
    BASE, auth, decide, ensure_user, pending_task, post_json, token,
)

pytestmark = pytest.mark.django_db


def make_position(title: str, *, with_employee: bool = True) -> Position:
    """Должность HR и — по умолчанию — активный сотрудник на ней.

    ``user_id`` сотрудника совпадает с id должности: так тесту не нужно
    держать две нумерации, а движку важно лишь то, что за должностью стоит
    активная учётная запись.
    """
    department, _ = Department.objects.get_or_create(
        path="seed-tests", defaults={"name": "Seed tests"})
    position = Position.objects.create(title=title, department=department,
                                       weight=Position.objects.count() + 1)
    if with_employee:
        user = ensure_user(position.pk)
        Employee.objects.create(
            user_id=user.pk, first_name=title, last_name="Tester",
            email=f"seed-{position.pk}@htq.test", department=department,
            position=position, hire_date="2024-01-01",
            status=EmployeeStatus.ACTIVE,
        )
    return position


def seed(**kwargs) -> str:
    out = StringIO()
    call_command("seed_purchase_request_template", stdout=out, **kwargs)
    return out.getvalue()


def test_seed_builds_the_form_from_the_cfo_note():
    seed()
    template = RequestFormTemplate.objects.get(slug=DEFAULT_SLUG)
    version = RequestFormTemplateVersion.objects.get(pk=template.current_version_id)
    fields = {f["key"]: f for f in version.schema_json["fields"]}

    # Шапка: «админ бюджета» + «программа» — это ОДНА строка бюджета.
    assert fields["budget_line"]["type"] == "budget_line_ref"
    assert fields["budget_line"]["required"] is True

    # Позиции — повторяемая группа с четырьмя колонками записки.
    items = fields["items"]
    assert items["type"] == "group" and items["repeatable"] is True
    columns = {f["key"]: f["type"] for f in items["fields"]}
    assert columns == {"name": "text", "quantity": "number",
                       "unit": "dropdown", "needed_by": "date"}
    unit = next(f for f in items["fields"] if f["key"] == "unit")
    assert unit["options"] == UNITS and "шт" in unit["options"]

    # Маршрута нет — и об этом сказано прямо.
    assert not ApprovalRoute.objects.exists()


def test_seed_is_idempotent_and_does_not_republish_an_unchanged_form():
    seed()
    version_id = RequestFormTemplate.objects.get(slug=DEFAULT_SLUG).current_version_id

    out = seed()
    assert "Шаблон уже есть" in out and "Форма не изменилась" in out
    assert RequestFormTemplate.objects.filter(slug=DEFAULT_SLUG).count() == 1
    assert RequestFormTemplateVersion.objects.count() == 1
    assert RequestFormTemplate.objects.get(slug=DEFAULT_SLUG).current_version_id == version_id


def test_seed_builds_the_buyer_checklist_and_the_cfo_stage_by_hr_positions():
    """Три шага закупщика → CFO, по ДОЛЖНОСТЯМ: сменится человек — маршрут
    не правят. Шаги закупщика — его чек-лист, поэтому каждый закрывается
    результатом: поставщик и условия — пояснением, счёт — файлом."""
    buyer, cfo = make_position("Закупщик"), make_position("Финансовый директор")
    out = seed(buyer=buyer.pk, cfo=cfo.pk)
    assert "Маршрут создан" in out

    template = RequestFormTemplate.objects.get(slug=DEFAULT_SLUG)
    route = ApprovalRoute.objects.get(scope=f"template:{template.pk}")
    stages = list(route.stages.order_by("order"))

    expected_names = [name for name, *_ in BUYER_STAGES] + [STAGE_CFO]
    assert [(s.order, s.name) for s in stages] == list(enumerate(expected_names, start=1))
    assert all(s.approver_kind == ApproverKind.POSITION for s in stages)
    assert [[r.position_id for r in s.roles.all()] for s in stages] == (
        [[buyer.pk]] * len(BUYER_STAGES) + [[cfo.pk]])

    # Требования шагов — ровно те, что объявлены в BUYER_STAGES; у CFO
    # требований нет: он утверждает по тому, что принёс закупщик.
    assert [(s.requires_attachment, s.requires_comment, s.requirement_key)
            for s in stages] == (
        [(f, c, r) for _, f, c, r in BUYER_STAGES] + [(False, False, "")])
    # Поставщик и сумма — требования к ЗАЯВКЕ (поля, которые заполняет
    # закупщик), счёт — к решению (файл). Файл — на последнем шаге: до
    # договорённости о цене его не существует.
    assert stages[0].requirement_key == "field:quotes"
    assert stages[1].requirement_key == "field:invoice"
    # Файл — на шаге счёта: до выбранного предложения его не существует.
    assert stages[1].requires_attachment is True
    assert stages[0].requires_attachment is False

    # Повторный запуск маршрут не трогает.
    assert "уже настроен" in seed(buyer=buyer.pk, cfo=cfo.pk)


def test_half_a_route_is_not_configured_at_all():
    """Один закупщик без CFO — другой процесс, а не «половина настройки»."""
    buyer = make_position("Закупщик")
    out = seed(buyer=buyer.pk)
    assert "Маршрут не настроен" in out
    assert not ApprovalRoute.objects.exists()


def test_a_position_nobody_holds_is_flagged_at_setup_time():
    """Движок проверяет наличие сотрудника на ЗАПУСКЕ — для разовой команды
    настройки это поздно, поэтому она предупреждает сразу."""
    empty = make_position("Закупщик", with_employee=False)
    cfo = make_position("Финансовый директор")
    out = seed(buyer=empty.pk, cfo=cfo.pk)
    assert "Маршрут создан" in out
    assert "нет активного сотрудника" in out and str(empty.pk) in out


def test_an_unknown_position_is_refused():
    cfo = make_position("Финансовый директор")
    with pytest.raises(Exception, match="Маршрут не принят"):
        seed(buyer=999999, cfo=cfo.pk)


def test_a_purchase_request_walks_the_buyer_checklist_then_the_cfo():
    """Инициатор подаёт без поставщика и суммы — их он знать не может.
    Закупщик заполняет их на своих шагах прямо в заявке, и шаг не
    закрывается, пока поле пустое. CFO видит поля, а не переписку."""
    buyer_position = make_position("Закупщик")
    cfo_position = make_position("Финансовый директор")
    buyer = User.objects.get(pk=buyer_position.pk)
    cfo = User.objects.get(pk=cfo_position.pk)
    seed(buyer=buyer_position.pk, cfo=cfo_position.pk)
    template = RequestFormTemplate.objects.get(slug=DEFAULT_SLUG)
    line = make_line()
    client = Client()
    # Инициатор с id, который не совпадёт ни с одной должностью: у
    # make_position учётка = pk должности, а те растут вместе с сиквенсом.
    INITIATOR = 900_001
    initiator = token(user_id=INITIATOR, sub=str(INITIATOR))

    created = post_json(client, f"{BASE}/instances/", {
        "template_id": template.pk,
        "title": "Ноутбуки для отдела",
        "form_values": {
            "budget_line": line.pk,
            "items": [{"name": "Ноутбук", "quantity": 2, "unit": "шт",
                       "needed_by": "2026-12-01"}],
            "purpose": "Замена вышедших из строя",
        },
    }, **auth(initiator))
    assert created.status_code == 201, created.content
    instance_id = created.json()["id"]

    # Подача проходит БЕЗ поставщика и суммы, хотя в схеме они required:
    # это поля закупщика, с инициатора их не спрашивают.
    submitted = client.post(f"{BASE}/instances/{instance_id}/submit/", **auth(initiator))
    assert submitted.status_code == 201, submitted.content

    from apps.approvals.models import RequestInstance
    instance = RequestInstance.objects.get(pk=instance_id)
    values_url = f"{BASE}/instances/{instance_id}/stage-values/"

    def fillable(user_id):
        return client.get(values_url, **auth(token(user_id=user_id, sub=str(user_id)))).json()

    def fill(user_id, values):
        return client.patch(values_url, data=json.dumps({"values": values}),
                            content_type="application/json",
                            **auth(token(user_id=user_id, sub=str(user_id))))

    # ── Шаг 1: сравнительная таблица ──
    assert pending_task(instance, buyer.pk).stage.name == BUYER_STAGES[0][0]
    step = fillable(buyer.pk)
    # Панель шага видит РОВНО своё поле, а не всё, что заполняет закупщик.
    assert (step["keys"], step["required_keys"]) == (["quotes"], ["quotes"])
    assert step["task_id"] == pending_task(instance, buyer.pk).pk
    assert step["stage_name"] == BUYER_STAGES[0][0]
    assert (step["requires_attachment"], step["requires_comment"]) == (False, False)
    # Инициатору и CFO заполнять нельзя — не их шаг.
    assert fillable(INITIATOR)["keys"] == [] and fillable(INITIATOR)["task_id"] is None
    assert fill(INITIATOR, {"quotes": {"suppliers": []}}).status_code == 409
    assert fill(cfo.pk, {"quotes": {"suppliers": []}}).status_code == 409

    # Пустая таблица шаг не закрывает — и отказ говорит, чего не хватает.
    refused = decide(client, instance, buyer.pk)
    assert refused.status_code == 409
    assert "хотя бы одно предложение" in refused.json()["detail"]

    # Предложения есть, цен нет — тоже не закрывает.
    assert fill(buyer.pk, {"quotes": {
        "suppliers": [{"name": "ИП Асқаров", "prices": []}]}}).status_code == 200
    refused = decide(client, instance, buyer.pk)
    assert refused.status_code == 409 and "заполнить цены" in refused.json()["detail"]

    # Цены есть, выбранный не отмечен — последнее, чего ждёт шаг.
    assert fill(buyer.pk, {"quotes": {
        "suppliers": [{"name": "ИП Асқаров", "prices": [200000, 40000]},
                      {"name": "ТОО «Дорого»", "prices": [300000, 60000]}],
    }}).status_code == 200
    refused = decide(client, instance, buyer.pk)
    assert refused.status_code == 409 and "отметить выбранного" in refused.json()["detail"]

    # Чужое поле на этом шаге не дают — с названием, а не молча.
    assert fill(buyer.pk, {"invoice": {"number": "187"}}).status_code == 409

    filled = fill(buyer.pk, {"quotes": {
        "suppliers": [{"name": "ИП Асқаров", "prices": [200000, 40000]},
                      {"name": "ТОО «Дорого»", "prices": [300000, 60000]}],
        "chosen": 0,
    }})
    assert filled.status_code == 200, filled.content
    # Итог вывел сервер: 200000×2 + 40000×1.
    table = filled.json()["form_values_json"]["quotes"]
    assert (table["total"], table["supplier_name"]) == ("400000", "ИП Асқаров")
    assert decide(client, instance, buyer.pk).status_code == 200

    # ── Шаг 2: счёт на ту же сумму + файл ──
    assert pending_task(instance, buyer.pk).stage.name == BUYER_STAGES[1][0]
    step = fillable(buyer.pk)
    assert step["keys"] == ["invoice"] and step["requires_attachment"] is True

    # Счёт на другую сумму шаг не закрывает — это и есть главная сверка.
    assert fill(buyer.pk, {"invoice": {"number": "187", "date": "2026-09-16",
                                       "amount": 500000}}).status_code == 200
    task = pending_task(instance, buyer.pk)
    task.file_id = "invoice-pdf"
    task.save(update_fields=["file_id"])
    refused = decide(client, instance, buyer.pk)
    assert refused.status_code == 409
    assert "суммы должны быть одинаковыми" in refused.json()["detail"]

    assert fill(buyer.pk, {"invoice": {"number": "187", "date": "2026-09-16",
                                       "amount": 400000}}).status_code == 200
    # Панель показывает, ЧТО приложено, — чтобы не тот счёт можно было
    # заметить и заменить до закрытия шага.
    step = fillable(buyer.pk)
    assert step["file_id"] == "invoice-pdf"
    assert "file_url" in step and "file_name" in step
    assert decide(client, instance, buyer.pk).status_code == 200
    instance.refresh_from_db()
    assert instance.status == RequestStatus.PENDING

    # ── CFO: последний, полей не заполняет ──
    # Задача у него есть (task_id), но этап ничего от заявки не требует —
    # ни поля, ни файла: это утверждение, а не рабочий шаг, панели нет.
    assert pending_task(instance, cfo.pk).stage.name == STAGE_CFO
    step = fillable(cfo.pk)
    assert step["keys"] == [] and step["requires_attachment"] is False
    assert step["task_id"] == pending_task(instance, cfo.pk).pk
    assert decide(client, instance, cfo.pk).status_code == 200
    instance.refresh_from_db()
    assert instance.status == RequestStatus.APPROVED
    assert instance.form_values_json["quotes"]["supplier_name"] == "ИП Асқаров"
    assert instance.form_values_json["invoice"]["number"] == "187"
    # Сумма заявки — итог выбранного предложения, а не сумма из счёта.
    assert str(instance.total_amount) == "400000.00"


def test_seed_refuses_a_route_with_an_inactive_approver():
    gone_a, gone_b = ensure_user(31, active=False), ensure_user(32, active=False)
    with pytest.raises(Exception, match="Маршрут не принят"):
        seed(buyer_user=gone_a.pk, cfo_user=gone_b.pk)
