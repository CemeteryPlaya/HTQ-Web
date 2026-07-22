"""Юнит-тест маппинга ``manage.py etl_requests`` (Фаза 10, ETL).

Лёгкий, изолированный тест: ``legacy_cursor`` мокается ``FakeCursor`` поверх
фикстурных dict-строк (НЕ бьёт настоящую legacy-БД) — только Django-сторона
идёт через настоящий (тестовый) Postgres, как и весь остальной проект.
Гоняется в изоляции:
``.venv/Scripts/python.exe -m pytest apps/approvals/tests/test_etl_requests.py -q``

Проверяется: (1) маппинг колонок для каждой смапленной таблицы создаёт
Django-объекты с верными полями, включая JSONB/Decimal/nullable и — САМОЕ
важное — что ``auto_now``/``auto_now_add`` поля (``created_at`` и т.п.)
реально несут ЛЕГАСИ-таймстемп, а не перезаписаны Django на "сейчас"
(см. module docstring ``etl_requests.py``); (2) ``row_hash`` совпадает
legacy-строка vs Django-объект для каждой смапленной таблицы; (3) идемпотент-
ность повторного прогона; (4) ``--dry-run`` ничего не пишет; (5) ``--verify``
даёт зелёный отчёт + печатает [SKIP]-строки реплик с их реальным count;
(6) ``--verify`` реально ловит расхождение (не тривиально всегда зелёный).
"""
from __future__ import annotations

import contextlib
import datetime as dt
import re
from decimal import Decimal

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.approvals.management.commands import etl_requests as cmd
from apps.approvals.models import (
    AuditLog,
    NotificationsLog,
    RequestActivity,
    RequestFormTemplate,
    RequestFormTemplateVersion,
    RequestInstance,
    RequestProject,
    RequestProjectMember,
    RequestReferenceRow,
    RequestReferenceSource,
    RequestStatsDaily,
    RequestWatcher,
)
from apps.core.etl import row_hash

_TS = dt.datetime(2024, 3, 1, 12, 0, 0, tzinfo=dt.timezone.utc)
_TS2 = dt.datetime(2024, 3, 2, 9, 30, 0, tzinfo=dt.timezone.utc)

# ── фикстурные legacy-строки: 1-2 строки на таблицу, покрывают весь домен ──

LEGACY_FIXTURES: dict[str, list[dict]] = {
    "request_projects": [
        {
            "id": 1, "name": "Командировки", "description": "Проект по командировкам",
            "status": "active", "color": "#3b82f6", "budget_limit": Decimal("500000.00"),
            "currency": "KZT", "start_date": dt.date(2024, 1, 1), "end_date": None,
            "owner_id": 11, "department_id": 3,
            "created_at": _TS, "updated_at": _TS,
        },
        {
            "id": 2, "name": "Закупки", "description": "", "status": "archived",
            "color": "#22c55e", "budget_limit": None, "currency": "KZT",
            "start_date": None, "end_date": None, "owner_id": None, "department_id": None,
            "created_at": _TS2, "updated_at": _TS2,
        },
    ],
    "request_project_members": [
        {"project_id": 1, "user_id": 21, "role": "admin", "granted_by": 11, "granted_at": _TS},
    ],
    "request_form_templates": [
        {
            "id": 1, "project_id": 1, "name": "Командировочные", "slug": "travel",
            "description": "", "icon": "plane", "color": "#3b82f6",
            "config_json": {"group": "hr", "who_can_submit": "all"},
            "is_active": True, "status": "active", "created_by": 11,
            "current_version_id": 1, "created_at": _TS, "updated_at": _TS,
        },
    ],
    "request_form_template_versions": [
        {
            "id": 1, "template_id": 1, "version": 1,
            "schema_json": {"fields": [{"key": "amount", "type": "money"}]},
            "workflow_json": {"nodes": [{"id": "n_start", "type": "start"}]},
            "published_at": _TS, "published_by": 11,
        },
    ],
    "request_instances": [
        {
            "id": 1, "code": "TRV-0001", "template_id": 1, "template_version_id": 1,
            "project_id": 1, "initiator_id": 21, "title": "Поездка в Астану",
            "status": "pending", "current_node_id": "n_app",
            "form_values_json": {"amount": 15000, "reason": "конференция"},
            "total_amount": Decimal("15000.00"), "currency": "KZT",
            "submitted_at": _TS, "finalized_at": None, "due_at": None,
            "requires_admin_attention": False, "created_at": _TS, "updated_at": _TS,
        },
    ],
    "request_approval_actions": [
        {
            "id": 1, "request_id": 1, "node_id": "n_app", "step_index": 0,
            "approver_id": 11, "assigned_at": _TS, "action": None, "comment": "",
            "acted_at": None, "due_at": None, "reminded_at": None, "reminders_sent": 0,
        },
    ],
    "request_activity": [
        {
            "id": 1, "request_id": 1, "actor_id": 21, "event_type": "submitted",
            "payload": {"from": "draft", "to": "pending"}, "created_at": _TS,
        },
    ],
    "request_watchers": [
        {"request_id": 1, "user_id": 30},
    ],
    "request_notifications_log": [
        {
            "id": 1, "request_id": 1, "recipient_id": 11, "kind": "new_request",
            "channel": "bot", "dedup_key": "req1:new_request:11", "created_at": _TS,
        },
    ],
    "request_reference_sources": [
        {
            "id": 1, "slug": "cities", "name": "Города", "columns_json": [{"key": "name"}],
            "created_by": 11, "template_id": 1, "access_ids": [11, 21],
            "created_at": _TS, "updated_at": _TS,
        },
    ],
    "request_reference_rows": [
        {"id": 1, "source_id": 1, "data_json": {"name": "Астана"}, "instance_id": None},
    ],
    "request_stats_daily": [
        {
            "date": dt.date(2024, 3, 1), "project_id": 1, "template_id": 1,
            "created": 1, "approved": 0, "rejected": 0, "cancelled": 0,
            "sum_approved_amount": Decimal("0.00"), "time_to_decision_seconds_sum": 0,
        },
    ],
    # Реплики без Django-цели — нужны, чтобы _SKIPPED_REPLICAS'ный legacy_count
    # в командe не упал (и чтобы проверить, что реальный count в [SKIP]-строке
    # печатается верно: 1 и 0).
    "request_users": [
        {"id": 11, "username": "boss", "email": "boss@htq.group", "first_name": "B",
         "last_name": "Boss", "is_active": True, "is_elevated": True,
         "deactivated_at": None},
    ],
    "request_departments": [],
}

_COUNT_RE = re.compile(r"count\(\*\)", re.IGNORECASE)
_TABLE_RE = re.compile(r'FROM\s+"\w+"\."(\w+)"', re.IGNORECASE)


class FakeCursor:
    """Дублирует протокол psycopg dict_row курсора (execute/fetchall/fetchone)
    поверх фикстур в памяти — ни один вызов не идёт в настоящую legacy-БД."""

    def __init__(self, fixtures: dict[str, list[dict]]):
        self._fixtures = fixtures
        self._pending: list[dict] = []
        self._is_count = False

    def execute(self, sql: str, params=None) -> None:
        match = _TABLE_RE.search(sql)
        assert match, f"FakeCursor: не нашёл имя таблицы в SQL: {sql!r}"
        table = match.group(1)
        rows = [dict(r) for r in self._fixtures.get(table, [])]
        self._is_count = bool(_COUNT_RE.search(sql))
        if not self._is_count and params:
            limit = params[0] if isinstance(params, (list, tuple)) else params
            rows = rows[:limit]
        self._pending = rows

    def fetchall(self) -> list[dict]:
        return self._pending

    def fetchone(self):
        if self._is_count:
            return {"n": len(self._pending)}
        return self._pending[0] if self._pending else None


@contextlib.contextmanager
def _fake_legacy_cursor(dsn: str | None = None):
    yield FakeCursor(LEGACY_FIXTURES)


@pytest.fixture(autouse=True)
def _patch_legacy_cursor(monkeypatch):
    """Подменяет legacy_cursor ИМЕННО в пространстве имён команды (импортирован
    туда через ``from apps.core.etl import legacy_cursor`` — патчить нужно
    там, где имя ищется, а не в apps.core.etl)."""
    monkeypatch.setattr(cmd, "legacy_cursor", _fake_legacy_cursor)


# ── маппинг колонок + row_hash ──────────────────────────────────────────

@pytest.mark.django_db
def test_migrate_creates_objects_with_correct_fields():
    call_command("etl_requests")

    project = RequestProject.objects.get(id=1)
    assert project.name == "Командировки"
    assert project.status == "active"
    assert project.budget_limit == Decimal("500000.00")
    assert project.owner_id == 11
    assert project.department_id == 3
    # Самое хрупкое место: auto_now_add/auto_now ДОЛЖНЫ нести легаси-таймстемп,
    # а не быть молча перезаписаны Django на timezone.now() при save() —
    # см. module docstring etl_requests.py.
    assert project.created_at == _TS
    assert project.updated_at == _TS

    project2 = RequestProject.objects.get(id=2)
    assert project2.budget_limit is None
    assert project2.owner_id is None
    assert project2.start_date is None

    template = RequestFormTemplate.objects.get(id=1)
    assert template.project_id == 1
    assert template.config_json == {"group": "hr", "who_can_submit": "all"}
    assert template.created_at == _TS

    version = RequestFormTemplateVersion.objects.get(id=1)
    assert version.template_id == 1
    assert version.schema_json == {"fields": [{"key": "amount", "type": "money"}]}
    assert version.published_at == _TS

    instance = RequestInstance.objects.get(id=1)
    assert instance.template_id == 1
    assert instance.project_id == 1
    assert instance.form_values_json == {"amount": 15000, "reason": "конференция"}
    assert instance.total_amount == Decimal("15000.00")
    assert instance.created_at == _TS

    member = RequestProjectMember.objects.get(project_id=1, user_id=21)
    assert member.role == "admin"
    assert member.granted_at == _TS

    watcher = RequestWatcher.objects.get(request_id=1, user_id=30)
    assert watcher.user_id == 30

    stats = RequestStatsDaily.objects.get(date=dt.date(2024, 3, 1), project_id=1,
                                          template_id=1)
    assert stats.created == 1

    activity = RequestActivity.objects.get(id=1)
    assert activity.payload == {"from": "draft", "to": "pending"}

    ref_source = RequestReferenceSource.objects.get(id=1)
    assert ref_source.access_ids == [11, 21]
    ref_row = RequestReferenceRow.objects.get(id=1)
    assert ref_row.data_json == {"name": "Астана"}

    notif = NotificationsLog.objects.get(id=1)
    assert notif.dedup_key == "req1:new_request:11"

    # AuditLog: нет legacy-источника — ETL ничего в неё не пишет.
    assert AuditLog.objects.count() == 0


@pytest.mark.django_db
def test_row_hash_matches_for_every_mapped_table():
    """Контрактное требование: row_hash(legacy) == row_hash(django) по КАЖДОЙ
    смапленной таблице (не только по паре ручных полей выше)."""
    call_command("etl_requests")

    checked = 0
    for spec in cmd.TABLE_SPECS:
        for row in LEGACY_FIXTURES.get(spec.table, []):
            lookup = {k: row[k] for k in spec.key}
            obj = spec.model.objects.get(**lookup)
            legacy_hash = row_hash(cmd._row_hash_dict(spec, row))
            django_hash = row_hash(cmd._obj_hash_dict(spec, obj))
            assert legacy_hash == django_hash, (
                f"hash mismatch for {spec.table} lookup={lookup}"
            )
            checked += 1
    # 12 смапленных таблиц дают ровно 10 непустых фикстурных строк выше
    # (request_watchers/request_stats_daily тоже по одной — считаем и их).
    assert checked == sum(len(LEGACY_FIXTURES.get(s.table, [])) for s in cmd.TABLE_SPECS)
    assert checked > 0


# ── идемпотентность ──────────────────────────────────────────────────────

@pytest.mark.django_db
def test_migrate_is_idempotent():
    call_command("etl_requests")
    first_created_at = RequestProject.objects.get(id=1).created_at
    counts_before = {
        "project": RequestProject.objects.count(),
        "template": RequestFormTemplate.objects.count(),
        "instance": RequestInstance.objects.count(),
        "member": RequestProjectMember.objects.count(),
        "watcher": RequestWatcher.objects.count(),
        "stats": RequestStatsDaily.objects.count(),
    }

    call_command("etl_requests")  # второй прогон — не должен ничего задублировать

    assert RequestProject.objects.count() == counts_before["project"]
    assert RequestFormTemplate.objects.count() == counts_before["template"]
    assert RequestInstance.objects.count() == counts_before["instance"]
    assert RequestProjectMember.objects.count() == counts_before["member"]
    assert RequestWatcher.objects.count() == counts_before["watcher"]
    assert RequestStatsDaily.objects.count() == counts_before["stats"]
    # Второй прогон идёт по update()-пути — таймстемп НЕ должен сдвинуться
    # на "сейчас" (в отличие от того, что сделал бы наивный .save()).
    assert RequestProject.objects.get(id=1).created_at == first_created_at


# ── --dry-run ────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_dry_run_writes_nothing():
    call_command("etl_requests", dry_run=True)

    assert RequestProject.objects.count() == 0
    assert RequestProjectMember.objects.count() == 0
    assert RequestFormTemplate.objects.count() == 0
    assert RequestFormTemplateVersion.objects.count() == 0
    assert RequestInstance.objects.count() == 0
    assert RequestWatcher.objects.count() == 0
    assert RequestStatsDaily.objects.count() == 0
    assert RequestReferenceSource.objects.count() == 0
    assert RequestReferenceRow.objects.count() == 0
    assert NotificationsLog.objects.count() == 0
    assert RequestActivity.objects.count() == 0


# ── --verify ─────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_verify_reports_green_with_skip_lines(capsys):
    call_command("etl_requests")
    call_command("etl_requests", verify=True)  # не должно бросить CommandError

    out = capsys.readouterr().out
    assert "ЗЕЛЁНЫЙ" in out
    assert "[SKIP] request_users (src=1" in out
    assert "[SKIP] request_departments (src=0" in out
    assert "audit_log" in out


@pytest.mark.django_db
def test_verify_detects_real_mismatch():
    call_command("etl_requests")

    tampered = RequestProject.objects.get(id=1)
    tampered.name = "ПОДМЕНЁННОЕ ИМЯ"
    tampered.save()

    with pytest.raises(CommandError):
        call_command("etl_requests", verify=True)
