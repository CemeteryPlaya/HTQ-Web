"""Бизнес-метрики учётных записей.

Собирается по расписанию через ``apps.core.metrics`` — см. докстринг там.
Обращается только к своим моделям (правило изоляции аппок).

``users_superusers`` — не про «сколько», а про «изменилось ли». Уровень («три
администратора») это норма, которая держится месяцами; событие — переход.
Поэтому правило алерта построено на ``changes()``, а не на пороге, ровно по
рецепту из шапки ``rules.yml``.

Гейдж уровня выбран сознательно вместо подсчёта событий в журнале аудита:
запись в аудит появляется только при выдаче прав через админ-API, а гейдж
ловит любой путь — ``manage.py createsuperuser``, ETL, прямой SQL.

Неудачные входы здесь отсутствуют: ``views.obtain_token`` при отказе не пишет
ни строки в базу (и не должен — эндпоинт неаутентифицированный, запись на
каждую попытку превратила бы его в усилитель отказа). Всплеск подбора ловится
по логам правилом ``htqweb-auth-failed-burst``.
"""
from __future__ import annotations

from django.db.models import Count
from django.utils import timezone

from .models import User, UserStatus

# Сколько часов заявка на регистрацию может ждать модерации, прежде чем это
# станет поводом сказать вслух. Двое суток — это «прошли выходные».
PENDING_STALE_HOURS = 48


def collect() -> dict:
    now = timezone.now()

    by_status = [((row["status"],), row["n"]) for row in
                 User.objects.values("status").annotate(n=Count("id"))]

    pending_stale = User.objects.filter(
        status=UserStatus.PENDING,
        date_joined__lt=now - timezone.timedelta(hours=PENDING_STALE_HOURS),
    ).count()

    superusers = User.objects.filter(
        is_superuser=True, status=UserStatus.ACTIVE).count()

    return {
        "users": {
            "help": "Учётные записи по статусам",
            "labels": ["status"],
            "values": by_status,
        },
        "users_pending_stale": {
            "help": ("Заявки на регистрацию, ждущие модерации дольше %d ч"
                     % PENDING_STALE_HOURS),
            "values": [((), pending_stale)],
        },
        "users_superusers": {
            "help": "Активные суперпользователи",
            "values": [((), superusers)],
        },
    }
