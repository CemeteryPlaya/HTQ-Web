"""Команда наполнения HR демо-данными — четыре оргструктуры документа.

Наполнение — такой же код, как остальной: если оно молча перестанет
связывать сотрудника с отделом его должности или дублировать записи при
повторном запуске, локальная база начнёт врать, а по ней потом смотрят
глазами и делают выводы.

Без ``--company`` команда сеет структуру HTQ в текущий ``search_path``
(режим перехода: единственная компания — HTQ). С ``--company`` — входит в
схему компании и сеет структуру её ``kind``.

Отдельно проверяется защита от неместной БД: ``DB_HOST`` по умолчанию
приходит из корневого ``.env``, где стоит боевой адрес.
"""

from __future__ import annotations

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.hr.management import group_structures as gs
from apps.hr.models import (
    Department, Employee, LevelThreshold, Position, ReportingRelation,
    StaffingPosition,
)


def _seed(**kwargs):
    call_command("seed_hr_demo", verbosity=0, **kwargs)


HTQ = gs.STRUCTURES["construction"]


@pytest.mark.django_db
def test_seed_without_company_is_the_construction_structure():
    _seed()
    assert LevelThreshold.objects.count() == 4
    assert set(Department.objects.values_list("path", flat=True)) == {"upr", "stroy"}
    assert set(Position.objects.values_list("title", flat=True)) == {p.title for p in HTQ.posts}
    assert Employee.objects.count() == 4
    assert ReportingRelation.objects.filter(relation_type="direct").count() == 3
    assert StaffingPosition.objects.count() == 4
    assert all(line.headcount == 1 for line in StaffingPosition.objects.all())


@pytest.mark.django_db
def test_seed_is_idempotent():
    _seed()
    counts = (LevelThreshold.objects.count(), Department.objects.count(),
              Position.objects.count(), Employee.objects.count(),
              ReportingRelation.objects.count(), StaffingPosition.objects.count())
    _seed()
    assert (LevelThreshold.objects.count(), Department.objects.count(),
            Position.objects.count(), Employee.objects.count(),
            ReportingRelation.objects.count(), StaffingPosition.objects.count()) == counts


@pytest.mark.django_db
def test_no_position_falls_into_the_default_level():
    _seed()
    for pos in Position.objects.all():
        assert pos.level == gs.level_for(pos.weight), pos.title
        assert pos.level != 5


@pytest.mark.django_db
def test_position_weight_conflict_from_a_previous_seed_is_a_clear_error():
    """Старый пятиуровневый сид на dev-базе держит «Генеральный директор» на
    весе 10 — том же, что новая структура HTQ хочет для «Директор». Отказ
    обязан называть конкретную пару «вес — чужая должность», а не падать
    сырым IntegrityError на уникальности веса."""
    dept = Department.objects.create(name="Старое", path="old-root")
    Position.objects.create(title="Генеральный директор", department=dept, weight=10)

    with pytest.raises(CommandError, match="Директор") as excinfo:
        _seed()

    assert "Генеральный директор" in str(excinfo.value)
    assert "вес 10" in str(excinfo.value)
    # Отказ — не половинчатая запись: до положений в этой же транзакции
    # ничего из демо-набора не осело.
    assert Employee.objects.count() == 0
    assert ReportingRelation.objects.count() == 0


@pytest.mark.django_db
def test_staffing_upserts_by_position_even_if_department_changed():
    """Симулируем перенос должности в другое подразделение вручную: старая
    штатная строка указывает на прежний отдел. Ключом обязан быть только
    ``position`` — иначе перенос заводит вторую строку вместо обновления
    существующей, и следующий прогон рискует упасть на
    ``MultipleObjectsReturned``."""
    _seed()
    director = Position.objects.get(title="Директор")
    other_dept = Department.objects.create(name="Другое", path="other-dept")
    StaffingPosition.objects.filter(position=director).delete()
    StaffingPosition.objects.create(position=director, department=other_dept, headcount=1)

    _seed()  # не должен ни упасть, ни задвоить строку

    rows = StaffingPosition.objects.filter(position=director)
    assert rows.count() == 1
    assert rows.first().department_id == director.department_id


@pytest.mark.django_db
def test_seed_retires_foreign_levels_and_recomputes_cached_levels():
    """Старый пятиуровневый сид на dev-базе: L5 (900–1999) пересёкся бы с
    N-4, а кэш уровня у старых должностей остался бы прежним."""
    dep = Department.objects.create(name="Старый", path="old")
    LevelThreshold.objects.create(level_number=5, weight_from=900, weight_to=1999)
    stale = Position.objects.create(title="Старая должность", department=dep,
                                    weight=950, level=5)
    _seed()
    assert not LevelThreshold.objects.filter(level_number=5).exists()
    stale.refresh_from_db()
    assert stale.level == 4


@pytest.mark.django_db
def test_employee_department_always_matches_their_position():
    _seed()
    mismatched = [e.email for e in Employee.objects.select_related("position")
                  if e.department_id != e.position.department_id]
    assert mismatched == []


@pytest.mark.django_db
def test_department_managers_work_in_their_own_department():
    _seed()
    for path, title in HTQ.managers.items():
        dept = Department.objects.get(path=path)
        assert dept.manager is not None, path
        assert dept.manager.position.title == title
        assert dept.manager.department_id == dept.id


@pytest.mark.django_db
def test_direct_relations_follow_the_document():
    _seed()
    by_title = {p.title: p for p in Position.objects.all()}
    for post in HTQ.posts:
        if post.reports_to is None:
            assert not ReportingRelation.objects.filter(
                subordinate_position=by_title[post.title]).exists()
            continue
        assert ReportingRelation.objects.filter(
            superior_position=by_title[post.reports_to],
            subordinate_position=by_title[post.title],
            relation_type="direct",
        ).exists(), post.title


@pytest.mark.django_db
def test_block_b_and_c_flags_come_from_the_structure():
    _seed()
    director = Position.objects.get(title="Директор")
    assert director.is_manager is True
    assert director.external_hierarchy == "none"
    assert not Position.objects.filter(serves_subsidiaries=True).exists()


@pytest.mark.django_db
def test_phones_use_the_platform_mask():
    import re
    _seed()
    mask = re.compile(r"^\+7 \(7\d\d\) \d{3}-\d\d-\d\d$")
    for e in Employee.objects.all():
        assert mask.match(e.phone), e.phone


def test_holding_seed_lays_out_the_substitution_matrix(company_schema):
    from django.core.cache import cache

    from apps.companies.models import Company
    from apps.hr.models import Substitution
    from htqweb.tenancy.db import use_company

    Company.objects.filter(slug=company_schema["slug"]).update(kind="holding")
    cache.clear()
    _seed(company=company_schema["slug"])
    with use_company(company_schema["slug"]):
        assert Substitution.objects.count() == 10
        assert Substitution.objects.filter(kind="primary").count() == 5
        ceo = Substitution.objects.get(position__title="Генеральный директор",
                                       kind="primary")
        assert ceo.substitute_position.title == "Операционный директор"
        assert ceo.basis.startswith("Приказ ГД / решение участника")
        assert not Substitution.objects.filter(
            position__title="Специалист технической поддержки").exists()


def test_substitution_seed_is_idempotent(company_schema):
    from django.core.cache import cache

    from apps.companies.models import Company
    from apps.hr.models import Substitution
    from htqweb.tenancy.db import use_company

    Company.objects.filter(slug=company_schema["slug"]).update(kind="holding")
    cache.clear()
    _seed(company=company_schema["slug"])
    _seed(company=company_schema["slug"])
    with use_company(company_schema["slug"]):
        assert Substitution.objects.count() == 10


def test_holding_seed_creates_the_participant_through_the_service(company_schema):
    from django.core.cache import cache

    from apps.companies.models import Company
    from htqweb.tenancy.db import use_company

    Company.objects.filter(slug=company_schema["slug"]).update(kind="holding")
    cache.clear()
    _seed(company=company_schema["slug"])
    with use_company(company_schema["slug"]):
        osu = Position.objects.get(title="Участник (ОСУ)")
        assert osu.is_system is True and osu.weight == 0
        assert osu.department.path == "osu" and osu.department.manager_id is None
        ceo = Position.objects.get(title="Генеральный директор")
        assert ReportingRelation.objects.filter(
            superior_position=osu, subordinate_position=ceo, relation_type="direct").exists()
        assert Employee.objects.filter(position=osu).count() == 1


@pytest.mark.django_db
def test_construction_structure_has_no_substitutions():
    _seed()
    from apps.hr.models import Substitution
    assert Substitution.objects.count() == 0


def test_seed_warns_about_the_document_row_it_cannot_express(company_schema, capsys):
    """Строка HR-FRM-006, которую нельзя выразить должностью, обязана быть
    названа вслух.

    Замещающий системного администратора в документе — внешний подрядчик, а
    не должность платформы. Это единственное место, где оператор стенда
    узнаёт, что строка утверждённого приказа осталась незакрытой; молчание
    здесь означало бы, что о ней просто забыли.
    """
    from django.core.cache import cache

    from apps.companies.models import Company

    Company.objects.filter(slug=company_schema["slug"]).update(kind="holding")
    cache.clear()
    call_command("seed_hr_demo", company=company_schema["slug"], verbosity=1)
    out = capsys.readouterr().out
    assert "Внутригрупповой ИТ-подрядчик" in out
    assert "Специалист технической поддержки" in out


# ── --company ────────────────────────────────────────────────────────────

def test_company_option_seeds_the_structure_of_its_kind(company_schema):
    """Фикстура заводит компанию kind=service → структура KEG, в её схеме."""
    from htqweb.tenancy.db import use_company

    _seed(company=company_schema["slug"])
    with use_company(company_schema["slug"]):
        assert set(Position.objects.values_list("title", flat=True)) == {
            "Директор", "Диспетчер", "Механик", "Водитель-оператор"}
        assert set(LevelThreshold.objects.values_list("level_number", flat=True)) == {1, 2, 3, 4}
    # public не тронут.
    assert Position.objects.count() == 0


def test_holding_structure_sets_serving_and_managing_flags(company_schema):
    from django.core.cache import cache

    from apps.companies.models import Company
    from htqweb.tenancy.db import use_company

    Company.objects.filter(slug=company_schema["slug"]).update(kind="holding")
    cache.clear()  # get_company кэширует 5 с
    _seed(company=company_schema["slug"])
    with use_company(company_schema["slug"]):
        assert Position.objects.filter(serves_subsidiaries=True).count() == 8
        # Блок F: is_manager=True, external_hierarchy="inherit" становится 5 (4 директора + ОСУ)
        assert Position.objects.filter(is_manager=True, external_hierarchy="inherit").count() == 5
        assert Department.objects.filter(unit_type="directorate").count() == 3
        assert ReportingRelation.objects.filter(relation_type="functional").count() == 3
        # Блок F: direct-связей 12 (ОСУ → ГД + 11 прежних)
        assert ReportingRelation.objects.filter(relation_type="direct").count() == 12


# ── роли должностей (задача 11 блока I) ─────────────────────────────────

def _seed_system_roles() -> None:
    """Четыре системные роли ``hr-*`` на месте — тем же приёмом, что
    ``apps/access/tests/test_backfill_positions.py::_seed_roles``: сид
    миграции ``access/0005`` как обычная функция (get_or_create внутри).
    Нужно, потому что транзакционные тесты соседних аппок flush'ат базу
    вместе с ролями, засеянными миграцией, а ``ensure_position_role`` без
    роли честно падает ``UnknownRole``."""
    import importlib
    from types import SimpleNamespace

    from django.apps import apps as django_apps

    migration = importlib.import_module("apps.access.migrations.0005_seed_hr_level_roles")
    migration.seed(django_apps, SimpleNamespace())


def test_company_seed_grants_position_roles_from_hr_level(company_schema):
    """После ``seed_hr_demo --company X`` у КАЖДОЙ должности с ``hr_level``
    есть ``PositionRole`` с ролью ``legacy_roles.ROLE_CODES[level]`` и
    областью ``legacy_roles.SCOPE_KINDS[level]`` — ровно то, что дал бы
    перенос ``access_backfill_positions`` по явной колонке. Повторный
    запуск не дублирует и не переписывает."""
    from apps.access.models import PositionRole
    from apps.hr import legacy_roles
    from htqweb.tenancy.db import use_company

    slug = company_schema["slug"]
    _seed_system_roles()
    _seed(company=slug)

    structure = gs.structure_for("service")  # kind фикстуры
    assert structure.posts, "структура без должностей — тест ничего не проверяет"
    with use_company(slug):
        by_title = {p.title: p.id for p in Position.objects.all()}

    for post in structure.posts:
        rows = list(PositionRole.objects.filter(
            company_slug=slug, position_id=by_title[post.title]).select_related("role"))
        assert len(rows) == 1, post.title
        assert rows[0].role.code == legacy_roles.ROLE_CODES[post.hr_level], post.title
        assert rows[0].role.is_system is True
        assert rows[0].scope_kind == legacy_roles.SCOPE_KINDS[post.hr_level], post.title

    snapshot = sorted(PositionRole.objects.filter(company_slug=slug)
                      .values_list("position_id", "role__code", "scope_kind"))
    _seed(company=slug)
    assert sorted(PositionRole.objects.filter(company_slug=slug)
                  .values_list("position_id", "role__code", "scope_kind")) == snapshot


def test_company_seed_keeps_a_scope_set_by_hand(company_schema):
    """Область, выставленная кадровиком руками, переживает пересев — сид
    не отменяет решение человека (тот же принцип, что у переноса)."""
    from apps.access.models import PositionRole
    from htqweb.tenancy.db import use_company

    slug = company_schema["slug"]
    _seed_system_roles()
    _seed(company=slug)
    with use_company(slug):
        director_id = Position.objects.get(title="Директор").id
    row = PositionRole.objects.get(company_slug=slug, position_id=director_id)
    assert row.scope_kind == "company"          # lead → компания по правилу
    PositionRole.objects.filter(pk=row.pk).update(scope_kind="department")

    _seed(company=slug)

    row.refresh_from_db()
    assert row.scope_kind == "department"
    assert PositionRole.objects.filter(company_slug=slug, position_id=director_id).count() == 1


@pytest.mark.django_db
def test_seed_without_company_grants_no_position_roles(capsys):
    """Режим перехода: компании нет — ``PositionRole`` ключуется по
    ``company_slug``, и выдавать роль некому. Шаг пропускается вслух, а не
    подставляет ``public`` за компанию."""
    from apps.access.models import PositionRole

    call_command("seed_hr_demo", verbosity=1)
    assert not PositionRole.objects.exists()
    out = capsys.readouterr().out
    assert "Роли должностей" in out and "пропущено" in out


def test_company_option_rejects_unknown_company(db):
    with pytest.raises(CommandError, match="не найдена"):
        _seed(company="t-no-such-company")


def test_company_option_rejects_a_company_without_schema(db):
    from apps.companies.models import Company, CompanyKind
    Company.objects.create(slug="t-orphan", name="Сирота", kind=CompanyKind.SERVICE)
    with pytest.raises(CommandError, match="схем"):
        _seed(company="t-orphan")


def test_company_option_rejects_legacy_regional_kind(company_schema):
    from django.core.cache import cache

    from apps.companies.models import Company

    Company.objects.filter(slug=company_schema["slug"]).update(kind="regional")
    cache.clear()
    with pytest.raises(CommandError, match="regional"):
        _seed(company=company_schema["slug"])


# --- защита от неместной БД -------------------------------------------------
#
# Проверяется как чистое правило от строки хоста, а НЕ подменой
# settings.DATABASES. Первая версия этих тестов писала боевой адрес в живые
# настройки; запись не ушла на VPS только потому, что соединение уже было
# открыто и Django его не переоткрывал, — зато тирдаун туда постучался и
# отвалился по таймауту. Полагаться на кеш соединения в тесте, который
# существует ради недопущения записи на бой, — противоречие. Хост теперь
# передаётся параметром, и адреса VPS в настройках не оказывается никогда.

def _guard(host: str, *, force: bool = False) -> None:
    from apps.hr.management.commands.seed_hr_demo import Command

    command = Command()
    command._assert_local(force, host=host)


@pytest.mark.django_db
def test_purge_removes_e2e_leftovers_only():
    """Очистка не должна задевать боевые (сидированные) записи.

    Опорная должность — «Директор» (глава HTQ по документу), а не
    «Генеральный директор» прежней структуры: с несуществующим названием
    утверждение выродилось бы в 0 == 0 и тест молча перестал бы что-либо
    проверять.
    """
    _seed()
    dept = Department.objects.create(name="E2E отдел мусор", path="e2e-junk")
    Position.objects.create(title="E2E должность мусор", department=dept,
                            weight=4_242_424)
    before_real = Position.objects.filter(title="Директор").count()
    assert before_real == 1, "опорная должность обязана существовать до очистки"

    _seed(purge_e2e=True)

    assert not Position.objects.filter(title__startswith="E2E ").exists()
    assert not Department.objects.filter(name__startswith="E2E ").exists()
    assert Position.objects.filter(title="Директор").count() == before_real
    assert Employee.objects.count() == 4, "засеянные сотрудники не должны исчезнуть"


@pytest.mark.parametrize("host", ["203.0.113.10", "db.example.com", "10.8.0.4"])
def test_refuses_to_run_against_a_remote_database(host):
    """Защита от опечатки в окружении. Команда пишет десятки строк — не то,
    что стоит случайно отправить на боевой хост."""
    with pytest.raises(CommandError, match="не похож на локальную"):
        _guard(host)


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "db", "::1", ""])
def test_local_hosts_pass_the_guard(host):
    _guard(host)  # не бросает


def test_force_remote_is_the_only_way_past_the_guard():
    _guard("203.0.113.10", force=True)  # не бросает


@pytest.mark.django_db
def test_guard_runs_before_anything_is_written(monkeypatch):
    """Отказ обязан случиться до первой записи, иначе «защита» оставит
    половину демо-данных на чужом хосте.

    Проверяется порядок вызовов, поэтому отказ подменяется, а не
    провоцируется настоящим адресом: чужой хост в настройках не нужен даже
    в виде документационного диапазона.
    """
    from apps.hr.management.commands import seed_hr_demo

    def refuse(self, force, host=None):
        raise CommandError("DB_HOST не похож на локальную БД")

    monkeypatch.setattr(seed_hr_demo.Command, "_assert_local", refuse)

    with pytest.raises(CommandError, match="не похож на локальную"):
        _seed()
    assert LevelThreshold.objects.count() == 0
    assert Department.objects.count() == 0


# ── блок F: Участник (ОСУ) ─────────────────────────────────────────────────

def test_holding_staffing_excludes_system_positions(company_schema):
    """ОСУ в документе — без штатной единицы; в счётчик «всего 12» не входит.
    Сид должен заводить штатные строки только для обычных должностей."""
    from django.core.cache import cache

    from apps.companies.models import Company
    from htqweb.tenancy.db import use_company

    Company.objects.filter(slug=company_schema["slug"]).update(kind="holding")
    cache.clear()
    _seed(company=company_schema["slug"])
    
    with use_company(company_schema["slug"]):
        # Количество должностей = 13 (12 обычных + 1 ОСУ)
        positions = Position.objects.all()
        assert positions.count() == 13
        
        # Штатных строк = 12 (только обычные, ОСУ исключена)
        staffing = StaffingPosition.objects.all()
        assert staffing.count() == 12
        
        # Проверяем, что ОСУ нет в штатном расписании
        osu = Position.objects.get(title="Участник (ОСУ)")
        assert not StaffingPosition.objects.filter(position=osu).exists()
        
        # Остальные 12 должностей в штатном расписании есть
        regular_positions = Position.objects.filter(is_system=False)
        assert regular_positions.count() == 12
        for pos in regular_positions:
            assert StaffingPosition.objects.filter(position=pos).exists(), pos.title
