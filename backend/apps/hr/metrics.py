"""Бизнес-метрики кадрового домена.

Собирается по расписанию через ``apps.core.metrics`` — см. докстринг там.
Обращается только к своим моделям (правило изоляции аппок).

Здесь сознательно мало метрик. Кадровые цифры — штатное расписание, вакансии,
закрытые заявки — это месячная отчётность, у неё есть свои экраны, и опрашивать
их раз в минуту незачем. В наблюдаемость вынесены только два состояния, каждое
из которых означает НЕИСПРАВНОСТЬ, а не величину:

* уволенный по дате сотрудник, оставшийся активным, — это открытый доступ у
  человека, которого в компании уже нет;
* активный сотрудник без учётной записи — причина, по которой согласование
  может встать намертво: движок signoff ищет исполнителей по должности через
  ``resolve_position_users``, и человек без ``user_id`` для него не существует.

Истечение документов, медосмотров и остаток отпуска здесь отсутствуют не по
недосмотру: таких колонок в схеме нет вовсе (сертификатные поля удалены
миграцией ``0016_remove_employeecard_certs``), и выразить их нечем.
"""
from __future__ import annotations

from django.db.models import Count
from django.utils import timezone

from .models import Employee, EmployeeStatus


def collect() -> dict:
    today = timezone.localdate()
    live = Employee.objects.filter(is_deleted=False)

    by_status = [((row["status"],), row["n"]) for row in
                 live.values("status").annotate(n=Count("id"))]

    # Дата увольнения прошла, а статус не переведён. Все проверки «активен ли
    # сотрудник» смотрят именно на status, поэтому такой человек продолжает
    # числиться работающим: остаётся согласующим в маршрутах и попадает в
    # выгрузки. Обязана быть нулём.
    terminated_still_active = live.filter(
        termination_date__lt=today).exclude(
        status=EmployeeStatus.TERMINATED).count()

    # Работает, но платформенной учётной записи нет. Не авария сама по себе
    # (человека могли не заводить намеренно), но именно отсюда берутся
    # «этап некому согласовать» и «задача не пришла».
    without_account = live.filter(status=EmployeeStatus.ACTIVE,
                                  user_id__isnull=True).count()

    return {
        "hr_employees": {
            "help": "Сотрудники по статусам (без удалённых)",
            "labels": ["status"],
            "values": by_status,
        },
        "hr_terminated_still_active": {
            "help": "Дата увольнения прошла, а статус не «уволен»",
            "values": [((), terminated_still_active)],
        },
        "hr_active_without_account": {
            "help": "Активные сотрудники без учётной записи на платформе",
            "values": [((), without_account)],
        },
    }
