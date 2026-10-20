"""Карточка сотрудника, заведённая вручную, не хранит пробелы по краям ФИО
(прод 12.10: «Ауелбаева  » в учётке и в карточке)."""
from datetime import date

from apps.hr import schemas


def test_create_schema_strips_names():
    data = schemas.EmployeeCreate(
        first_name=" Ерболат ", last_name="Гайбуллаев  ", middle_name=" Заирович ",
        email="erbolat@htq.test", department_id=1, position_id=1, hire_date=date(2026, 6, 16),
    )
    assert (data.first_name, data.last_name, data.middle_name) == (
        "Ерболат", "Гайбуллаев", "Заирович")


def test_update_schema_strips_names_and_keeps_patch_semantics():
    assert schemas.EmployeeUpdate(last_name=" Ауелбаева  ").last_name == "Ауелбаева"
    # PATCH без ФИО по-прежнему ничего не трогает.
    assert schemas.EmployeeUpdate().model_dump(exclude_none=True) == {}
