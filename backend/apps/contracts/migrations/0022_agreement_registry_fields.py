"""Колонки под реестр договоров заказчика + перевод ``Program`` на код.

Готовит модели к ``manage.py import_cashflow`` (см.
``apps/contracts/services/cashflow_import.py``): в книге финансистов есть
три факта, которым в моделях места не было, и один ключ, который стоял не
на том поле.

## Договор: три новые колонки и одна служебная

- ``advance_share`` — доля аванса из колонки «Аванс (ТИП ОПЛАТЫ)».
  ``payment_type`` из неё выводится, но не заменяет: тип — три ветки логики,
  доля — цифра.
- ``kind`` («Вид»: РиУ / ТМЦ) и ``contract_type`` («Тип»: стандарт /
  открытый). Второй несёт вес: у открытых договоров суммы нет по существу,
  и без этого признака их ``amount = 0`` читался бы как потеря данных.
- ``external_id`` — идентификатор договора в системе-источнике (LARK).
  Не бизнес-поле: по нему последующие импорты («Операции») находят уже
  загруженный договор. Номер для этого не годится — он в реестре
  повторяется, и импорт правит повторы точкой.

Все четыре с ``db_default``, поэтому на существующих строках заполняются без
отдельного прохода данных.

## Программа: ключ переезжает с названия на код

Было ``UniqueConstraint(name, expense_item)``, стало
``UniqueConstraint(code)`` с условием на непустой код. Причина — в данных:
разные программы разных проектов регулярно называются одинаково
(«Сопровождение проекта» — это и 3011, и 3020), и уникальность по названию
не пустила бы в базу вторую. Различает их ``display_name`` («код
название»), так что в интерфейсе двусмысленности не возникает.

Условие ``~Q(code="")`` обязательно: ``code`` необязателен, а пустые строки
Postgres считает равными — без условия все заведённые руками программы без
кода конфликтовали бы между собой.

⚠️ Если в базе уже есть программы с одинаковым непустым кодом, миграция
упадёт на создании индекса. Это намеренно: молча слить две программы в
одну — потерять привязку бюджетных строк к правильной из них.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("contracts", "0019_advance_report")]

    operations = [
        migrations.AddField(
            model_name="agreement",
            name="advance_share",
            field=models.DecimalField(db_default=0, decimal_places=3, default=0,
                                      max_digits=4, verbose_name="Доля аванса"),
        ),
        migrations.AddField(
            model_name="agreement",
            name="kind",
            field=models.CharField(
                choices=[("works_services", "Работы и услуги (РиУ)"),
                         ("goods", "Товарно-материальные ценности (ТМЦ)")],
                db_default="works_services", default="works_services",
                max_length=20, verbose_name="Вид",
            ),
        ),
        migrations.AddField(
            model_name="agreement",
            name="contract_type",
            field=models.CharField(
                choices=[("standard", "Стандартный"), ("open", "Открытый")],
                db_default="standard", default="standard",
                max_length=16, verbose_name="Тип",
            ),
        ),
        migrations.AddField(
            model_name="agreement",
            name="external_id",
            field=models.CharField(blank=True, db_default="", db_index=True,
                                   default="", max_length=64,
                                   verbose_name="Идентификатор в источнике"),
        ),
        migrations.AddConstraint(
            model_name="agreement",
            constraint=models.UniqueConstraint(
                condition=models.Q(("external_id", ""), _negated=True),
                fields=("external_id",), name="uq_contracts_agr_external_id",
            ),
        ),
        migrations.AddConstraint(
            model_name="agreement",
            constraint=models.CheckConstraint(
                condition=models.Q(("advance_share__gte", 0), ("advance_share__lte", 1)),
                name="ck_contracts_agr_advance_share",
            ),
        ),
        migrations.RemoveConstraint(
            model_name="program",
            name="uq_contracts_program_name_item",
        ),
        migrations.AddConstraint(
            model_name="program",
            constraint=models.UniqueConstraint(
                condition=models.Q(("code", ""), _negated=True),
                fields=("code",), name="uq_contracts_program_code",
            ),
        ),
    ]
