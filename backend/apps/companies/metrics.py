"""Бизнес-метрики реестра компаний.

Соглашение то же, что у остальных apps/<domain>/metrics.py: apps.core.metrics
находит и сливает этот collect() сам, межаппных импортов не возникает.
Считается Celery-beat'ом раз в 60 секунд в кэш, а не на скрейп.

Отставание схемы — не авария: разные компании намеренно обновляются с разной
скоростью (см. expand/contract). Метрика нужна, чтобы отставание было ВИДНО;
порог алерта задаётся в Grafana, а не здесь.

Форма возврата — та же, что у apps/conference/metrics.py: словарь
{имя: {"help", "labels"?, "values": [(кортеж_меток, число)]}}, имена БЕЗ
префикса htqweb_ (его добавляет apps.core.metrics при экспорте).
"""

from __future__ import annotations

from django.db.models import Count, F

from .models import Company, CompanySchemaVersion, CompanyStatus


def collect() -> dict:
    by_kind = (Company.objects
               .filter(status=CompanyStatus.ACTIVE)
               .values("kind")
               .annotate(n=Count("id"))
               .order_by("kind"))
    archived = Company.objects.filter(status=CompanyStatus.ARCHIVED).count()

    # Пустая target_migration означает «прогона ещё не было» — это не
    # отставание, а отсутствие данных, и считать его отставанием значило бы
    # поднимать тревогу на каждой только что заведённой компании.
    behind = (CompanySchemaVersion.objects
              .exclude(target_migration="")
              .exclude(applied_migration=F("target_migration"))
              .count())
    errors = CompanySchemaVersion.objects.exclude(last_error="").count()

    return {
        "companies_active_by_kind": {
            "help": "Действующие компании по типу",
            "labels": ["kind"],
            "values": [((row["kind"],), row["n"]) for row in by_kind],
        },
        "companies_archived": {
            "help": "Компании в архиве",
            "values": [((), archived)],
        },
        "company_schemas_behind": {
            "help": "Схемы компаний, отставшие от целевой миграции",
            "values": [((), behind)],
        },
        "company_schema_errors": {
            "help": "Схемы компаний с ошибкой последнего прогона миграций",
            "values": [((), errors)],
        },
    }
