"""Одно правило про пару дат — и в схеме, и в сервисе.

Живёт в ``htqweb``, а не в аппке, потому что пара дат есть уже у двух:
``apps.tasks`` (блок, роудмап, задача, проект, привлечение, потребность) и
``apps.approvals`` (проект). Положи правило в одну из них — вторая полезла бы
к соседке напрямую, а это запрещено (``apps/core/tests/test_app_isolation.py``).

Правило тривиально: конец не раньше начала. Нетривиально то, ГДЕ его
проверять, и почему одного места мало.

В БД оно уже стоит четырьмя ``CheckConstraint`` (``ck_site_block_dates``,
``ck_roadmap_planned_dates``, ``ck_engagement_dates``, ``ck_requirement_dates``,
``ck_task_dates``). База — последний рубеж, и срабатывает она
``IntegrityError``, то есть 500-й: ``htqweb.http`` заворачивает любое
исключение в «внутреннюю ошибку сервера». Авторы схем это понимали и ставили
``model_validator`` на создание с прямой пометкой «здесь это 422 с текстом, а
не IntegrityError→500» — но только на создание.

Отсюда два уровня, и оба нужны:

* **Схема** ловит запрос, в котором обе даты приехали вместе. Это обычный
  случай формы: она шлёт оба поля. Отказ — 422 с текстом, без похода в базу.
* **Сервис** ловит ЧАСТИЧНУЮ правку. ``PATCH`` с одним только ``end_date``
  схема проверить не может: второй даты в запросе нет, а лежит она в строке.
  Сервисы устроены одинаково (загрузить → ``setattr`` → ``save``), поэтому
  перед сохранением у них на руках уже СЛИТОЕ состояние — единственное место,
  где правило проверяемо целиком.

Без второго уровня дыра остаётся открытой, причём в самом неприятном виде:
``_update_block`` ловит ``IntegrityError`` и отвечает 409 «Блок с таким
названием или кодом уже есть на этом объекте». То есть человек, поправивший
даты, получал бы сообщение про дубль имени.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, model_validator

#: Текст один на все сущности: правило одно, и разными словами объяснять его
#: незачем. Схемы отдают его как 422, сервисы — через ``DatesOutOfOrder``.
MESSAGE = "Дата начала позже даты окончания"

#: Пары полей, которыми даты названы в разных сущностях, и текст отказа для
#: каждой. Список закрытый: новая пара — новая строка здесь, иначе схему не
#: проверит ни один уровень (за этим следит
#: ``apps/core/tests/test_invariants.py``).
DATE_PAIRS: tuple[tuple[str, str, str], ...] = (
    ("start_date", "end_date", MESSAGE),
    ("planned_start_date", "planned_end_date",
     "Плановая дата начала позже даты окончания"),
    ("start_date", "due_date", MESSAGE),
    ("from_date", "to_date", "Дата начала участия позже даты окончания"),
    ("valid_from", "valid_to", MESSAGE),
)


class DatesOutOfOrder(Exception):
    """422 — конец раньше начала.

    Отдельный класс, а не ``ValueError``: часть вьюх ловит ``ValueError`` и
    отвечает 409 «занято» или 400. Попади правило дат в ту же ветку, человек
    получил бы сообщение не про то.
    """

    def __init__(self, message: str = MESSAGE) -> None:
        super().__init__(message)


def out_of_order(start: date | None, end: date | None) -> bool:
    """``True``, только когда обе даты заданы и порядок нарушен."""
    return bool(start and end and start > end)


def assert_ordered(start: date | None, end: date | None,
                   message: str = MESSAGE) -> None:
    """Бросает ``DatesOutOfOrder``; вьюха переводит его в 422."""
    if out_of_order(start, end):
        raise DatesOutOfOrder(message)


class OrderedDates(BaseModel):
    """Примесь «конец не раньше начала» для схем с парой дат.

    Проверяет ВСЕ пары из ``DATE_PAIRS``, поэтому одна примесь годится и блоку
    (``start_date``/``end_date``), и роудмапу (``planned_*``), и задаче
    (``start_date``/``due_date``).

    Подмешивается и к ``*Create``, и к ``*Update``. У ``*Update`` она ловит
    только случай «обе даты приехали в одном запросе» — этого достаточно для
    формы, которая шлёт оба поля. Частичный ``PATCH`` схеме не виден и
    закрывается в сервисе (``assert_instance_ordered``).
    """

    @model_validator(mode="after")
    def _dates_are_ordered(self):
        for start_name, end_name, message in DATE_PAIRS:
            if out_of_order(getattr(self, start_name, None),
                            getattr(self, end_name, None)):
                raise ValueError(message)
        return self


def assert_instance_ordered(instance: object) -> None:
    """Проверить все известные пары дат у уже слитого объекта модели.

    Вызывается в сервисе перед ``save()``: к этому моменту ``setattr`` уже
    наложил изменения на загруженную строку, и видны обе даты — и присланная,
    и сохранённая ранее.
    """
    for start_name, end_name, message in DATE_PAIRS:
        assert_ordered(getattr(instance, start_name, None),
                       getattr(instance, end_name, None), message)
