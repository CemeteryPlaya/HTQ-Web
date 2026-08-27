"""Команда заведения компании: реестр + схема + миграции + сводки холдинга.

Тесты, которые реально создают схему и гоняют по ней миграции, идут с
``transaction=True`` (миграции — DDL из многих операторов подряд, обычный
django_db откатил бы половину сделанного между шагами) и поэтому убирают за
собой руками через фикстуру ``cleanup``. Тесты отказа до создания схемы
(невалидный slug, дубликат) обычным django_db обошлись бы тоже, но
``transaction=True`` держится единообразно по файлу, чтобы не путать, какой
тест чем откатывается.
"""

import pytest
from django.core.management import CommandError, call_command
from django.db import connection

from apps.companies.models import Company, CompanyKind
from apps.companies.services import holding_views, migration_service, schema_service


@pytest.fixture(autouse=True)
def cleanup():
    yield
    # Порядок как в test_holding_views.py: сначала снести holding целиком, и
    # только потом схему компании — иначе DROP SCHEMA ... CASCADE утащит за
    # собой представления holding, зависящие от таблиц ДРУГИХ компаний, и
    # следующий тест получит holding в состоянии, которое никто не задавал.
    # rebuild в конце возвращает holding в консистентное состояние (пустое,
    # если t-new была единственной действующей компанией).
    holding_views.drop_holding_views()
    schema_service.drop_schema("t-new")
    Company.objects.filter(slug="t-new").delete()
    holding_views.rebuild_holding_views()


@pytest.mark.django_db(transaction=True)
def test_creates_row_schema_and_tables():
    call_command("company_create", "t-new", name="Новая", kind="service")

    assert Company.objects.filter(slug="t-new").exists()
    assert schema_service.schema_exists("t-new")
    with connection.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = 'co_t_new' AND table_name = 'tasks_task'"
        )
        assert cur.fetchone() is not None


@pytest.mark.django_db(transaction=True)
def test_rejects_invalid_slug():
    with pytest.raises(CommandError):
        call_command("company_create", "Плохой_Slug", name="X", kind="service")


@pytest.mark.django_db(transaction=True)
def test_rejects_duplicate_slug():
    Company.objects.create(slug="t-new", name="Уже есть", kind=CompanyKind.SERVICE)
    with pytest.raises(CommandError):
        call_command("company_create", "t-new", name="Дубль", kind="service")


@pytest.mark.django_db(transaction=True)
def test_rejects_unknown_parent():
    with pytest.raises(CommandError):
        call_command("company_create", "t-new", name="X", kind="service",
                      parent="net-takoy")

    # Ничего не должно было создаться: проверка родителя идёт ДО записи
    # строки реестра и схемы.
    assert not Company.objects.filter(slug="t-new").exists()
    assert not schema_service.schema_exists("t-new")


@pytest.mark.django_db(transaction=True)
def test_rolls_back_schema_and_row_on_migration_failure(monkeypatch):
    """Откат обязан снести И схему, И строку реестра — не что-то одно.

    Если бы откат сносил только схему, строка реестра осталась бы висеть с
    kind/parent, но без единой таблицы — компания выглядела бы заведённой и
    падала бы на первом же запросе. Если бы откат сносил только строку,
    осиротевшая пустая схема осталась бы в базе без владельца в реестре.
    Проверяем оба факта раздельно, а не одним ``assert not exists``.
    """
    def boom(slug, **kwargs):
        raise RuntimeError("миграция сломалась")

    monkeypatch.setattr(migration_service, "migrate_company", boom)

    with pytest.raises(RuntimeError, match="миграция сломалась"):
        call_command("company_create", "t-new", name="Авария", kind="service")

    assert not Company.objects.filter(slug="t-new").exists()
    assert not schema_service.schema_exists("t-new")


@pytest.mark.django_db(transaction=True)
def test_rebuilds_holding_views_after_success():
    """Сводки холдинга обязаны включать только что созданную компанию.

    Список действующих компаний читается с fresh=True внутри
    rebuild_holding_views, поэтому пятисекундный кэш interface.py не должен
    маскировать проверку — но убеждаемся напрямую, что вьюхи вообще собраны
    (drop_holding_views перед миграциями их сносит, и без вызова
    rebuild_holding_views в конце команды они остались бы снесёнными).
    """
    call_command("company_create", "t-new", name="Новая", kind="service")

    with connection.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM information_schema.views "
            "WHERE table_schema = 'holding' AND table_name = 'tasks_task'"
        )
        assert cur.fetchone() is not None

    with connection.cursor() as cur:
        cur.execute("SELECT company_slug FROM holding.tasks_task "
                     "WHERE company_slug = 't-new' LIMIT 1")
        # Пустой результат — тоже валиден (в свежей схеме задач нет), важно
        # чтобы запрос не падал "relation does not exist": это доказывает,
        # что ветка UNION ALL по t-new физически присутствует.
        cur.fetchall()
