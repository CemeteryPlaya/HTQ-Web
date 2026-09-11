"""Колонки под реестр договоров заказчика + перевод ``Program`` на код.

Готовит модели к ``manage.py import_cashflow`` (см.
``apps/contracts/services/cashflow_import.py``): в книге финансистов есть
факты, которым в моделях места не было, и один ключ, который стоял не на том
поле.

## Договор: две новые колонки

- ``advance_share`` — доля аванса из колонки «Аванс (ТИП ОПЛАТЫ)».
  ``payment_type`` из неё выводится, но не заменяет: тип — три ветки логики,
  доля — цифра.
- ``external_id`` — идентификатор договора в системе-источнике (LARK).
  Не бизнес-поле: по нему последующие импорты («Операции») находят уже
  загруженный договор. Номер для этого не годится — он в реестре
  повторяется, и импорт правит повторы точкой.

Обе с ``db_default``, поэтому на существующих строках заполняются без
отдельного прохода данных.

⚠️ ``kind`` и ``contract_type`` («Вид» и «Тип» реестра) здесь НЕ добавляются,
хотя реестру нужны и они: их заводит ``0020_agreement_advance_amount_planned_
and_more`` — та же пара колонок пришла второй веткой, из карточки договора, и
с более широким набором значений. Повторный ``AddField`` упал бы на уже
существующей колонке. «Открытому» договору реестра соответствует
``AgreementType.FRAMEWORK`` — одно понятие под двумя именами, см. докстринг
``AgreementType``.

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

    # 0021, а НЕ 0019: изначально эта миграция была вторым номером 0020 и
    # висела второй ветвью от 0019 — два листа в графе, на которых `migrate`
    # отказывается работать целиком («Conflicting migrations detected»).
    # Перенумерована в 0022 и поставлена в линию.
    dependencies = [("contracts", "0021_administrator_project_id")]

    operations = [
        migrations.AddField(
            model_name="agreement",
            name="advance_share",
            field=models.DecimalField(db_default=0, decimal_places=3, default=0,
                                      max_digits=4, verbose_name="Доля аванса"),
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
