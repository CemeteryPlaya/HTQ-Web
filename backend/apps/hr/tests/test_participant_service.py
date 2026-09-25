"""Системная должность «Участник (ОСУ)».

ОСУ в документах — орган владельцев над генеральным директором, без штатной
единицы. В платформе это должность с ``is_system=True``: её нельзя
переименовать, перевести или удалить через интерфейс, а маршрут
согласования может сослаться на неё обычным ``position_id``. Заводится
ровно одним способом — этим сервисом, — чтобы стенд и бой не разъехались.
"""

from __future__ import annotations

import pytest

from apps.hr.models import Department, ExternalHierarchy, Position, UnitType
from apps.hr.services import participant_service as svc
from apps.hr.services import position_service


@pytest.mark.django_db
def test_creates_the_unit_and_the_system_position():
    position, created = svc.ensure_participant()
    assert created is True
    assert position.title == "Участник (ОСУ)"
    assert position.is_system is True
    assert position.weight == 0
    assert position.department.path == "osu"
    assert position.department.name == "Общее собрание участников"
    assert position.department.unit_type == UnitType.DEPARTMENT
    assert position.department.manager_id is None


@pytest.mark.django_db
def test_participant_oversees_the_group_but_does_not_serve_it():
    """Владелец видит дочерние компании (блок B), но не «обслуживает» их
    (блок C): права в ДО ему раздаются членством и ролями, как любому."""
    position, _ = svc.ensure_participant()
    assert position.is_manager is True
    assert position.external_hierarchy == ExternalHierarchy.INHERIT
    assert position.serves_subsidiaries is False
    # ``permissions`` не проставляется вовсе (задача 9 блока I: колонка
    # мертва для авторизации, ``ensure_participant`` её больше не пишет).
    assert position.permissions is None


@pytest.mark.django_db
def test_level_is_computed_from_thresholds_not_hardcoded():
    """Уровень — кэш от веса через пороги, не литерал: с порогом N-1 (0–99)
    вес 0 попадает в уровень 1; без порогов был бы запасной 5 — и тест,
    написанный без порога, не отличил бы одно от другого."""
    from apps.hr.models import LevelThreshold

    LevelThreshold.objects.create(level_number=1, weight_from=0, weight_to=99, label="N-1")
    position, _ = svc.ensure_participant()
    assert position.level == 1
    assert position.level == position_service._compute_level(0)


@pytest.mark.django_db
def test_is_idempotent_and_repairs_drift():
    first, created = svc.ensure_participant()
    assert created
    # Кто-то через ORM снял руководящий признак и поменял грейд — повторный
    # вызов возвращает ОСУ в предписанное состояние, не плодя вторую строку.
    Position.objects.filter(pk=first.pk).update(is_manager=False, grade=3)
    second, created_again = svc.ensure_participant()
    assert created_again is False
    assert second.pk == first.pk
    # ВАЖНО: перечитываем из БД, чтобы проверить действительно ли сохранены изменения
    second.refresh_from_db()
    assert second.is_manager is True, "is_manager должно быть восстановлено"
    assert second.grade == 10, "grade должно быть восстановлено"
    assert Position.objects.filter(title="Участник (ОСУ)").count() == 1
    assert Department.objects.filter(path="osu").count() == 1


@pytest.mark.django_db
def test_refuses_when_weight_zero_belongs_to_someone_else():
    """Вес 0 — вершина шкалы. Если его уже держит другая должность, молча
    подвинуть её нельзя: это чужие данные."""
    dep = Department.objects.create(name="Руководство", path="upr")
    Position.objects.create(title="Председатель", department=dep, weight=0)
    with pytest.raises(svc.ParticipantWeightTaken) as exc:
        svc.ensure_participant()
    assert "Председатель" in exc.value.detail
    assert not Position.objects.filter(title="Участник (ОСУ)").exists()
    # Подразделение ОСУ тоже не создано при отказе.
    assert not Department.objects.filter(path="osu").exists()


@pytest.mark.django_db
def test_find_participant_returns_none_when_absent():
    assert svc.find_participant() is None
    position, _ = svc.ensure_participant()
    assert svc.find_participant().pk == position.pk


@pytest.mark.django_db
def test_system_position_is_locked_for_ui_edits():
    """Смысл is_system: через API нельзя переименовать, перевести и
    деактивировать, нельзя удалить — иначе маршрут согласования, который
    ссылается на ОСУ, однажды укажет в пустоту."""
    from apps.hr import schemas

    position, _ = svc.ensure_participant()
    with pytest.raises(position_service.SystemPositionFieldsLocked):
        position_service.update_position(
            position.id, schemas.PositionUpdate(title="Совет"))
    with pytest.raises(position_service.SystemPositionProtected):
        position_service.delete_position(position.id)


@pytest.mark.django_db
def test_refuses_when_title_already_taken_by_normal_position():
    """Кадровик завёл обычную должность с названием ОСУ. Системная должность
    должна отказать, пока чужую не переименуют."""
    dep = Department.objects.create(name="Отдел", path="dept")
    Position.objects.create(title="Участник (ОСУ)", department=dep, weight=50)
    
    with pytest.raises(svc.ParticipantTitleConflict) as exc:
        svc.ensure_participant()
    assert "зарезервирована" in exc.value.detail
    assert "Переименуйте" in exc.value.detail
    # ОСУ не создана.
    assert not Position.objects.filter(is_system=True).exists()
    # Подразделение ОСУ тоже не создано.
    assert not Department.objects.filter(path="osu").exists()


@pytest.mark.django_db
def test_refuses_when_unit_name_already_taken_by_normal_department():
    """Кадровик завёл обычное подразделение с названием ОСУ. Системное подразделение
    должно отказать, пока чужое не переименуют."""
    Department.objects.create(name="Общее собрание участников", path="other-path")
    
    with pytest.raises(svc.ParticipantUnitConflict) as exc:
        svc.ensure_participant()
    assert "зарезервировано" in exc.value.detail
    assert "Переименуйте" in exc.value.detail
    # ОСУ не создана.
    assert not Position.objects.filter(is_system=True).exists()
    # Подразделение ОСУ не создано.
    assert not Department.objects.filter(path="osu").exists()


@pytest.mark.django_db
def test_refuses_both_title_and_unit_conflicts():
    """Если конфликтуют оба, отказываем на первой (title)."""
    dep1 = Department.objects.create(name="Участник (ОСУ)", path="path1")
    dep2 = Department.objects.create(name="Общее собрание участников", path="path2")
    Position.objects.create(title="Участник (ОСУ)", department=dep1, weight=50)
    
    # Первый отказ — на title
    with pytest.raises(svc.ParticipantTitleConflict):
        svc.ensure_participant()
