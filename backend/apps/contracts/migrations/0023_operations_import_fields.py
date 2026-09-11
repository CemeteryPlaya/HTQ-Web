"""Ключ программы «код + название» и поля под импорт листа «Операции».

## Программа: ключ ``code`` → ``(code, name)``

``0022`` сделал ключом программы один код — реестр договоров это позволял.
Лист «Операции» показал, что коды у финансистов СВОИ У КАЖДОГО ПРОЕКТА:
111 — «Материально-техническое оснащение» у офиса и «Мобилизация» у
ВАрваринского, 3026 — «Кабели LV» у Аральска и «Система заземления» у
«Арал 30 МВт». Уникальный код не пустил бы вторую из каждой пары.

Новый ключ СЛАБЕЕ прежнего (всякая пара, уникальная по коду, уникальна и по
«код + название»), поэтому на любых уже загруженных данных миграция пройти
обязана — отсюда и то, что ``0022`` не правится, а перекрывается этой:
``0022`` уже применена на проде.

Заодно возвращается правило, которое ``0022`` снял вместе со старым ключом:
программа БЕЗ кода уникальна по «название + статья», как было до кодов.
Снят он был по недосмотру — без него две одинаковые программы, заведённые
руками, ложатся в базу дважды. ⚠️ Если за время между ``0022`` и этой
миграцией такие дубли на проде успели завести, создание индекса упадёт —
их нужно слить руками до применения.

## Счёт и оплата по договору: дата документа и идентификатор источника

- ``document_date`` — дата самого счёта, а не его записи в платформу.
- ``external_id`` — по нему повторный прогон импорта находит свою строку.
  Уникален только среди непустых: записи, заведённые руками, источника не
  имеют.

Всё с ``db_default``/``null``, поэтому существующие строки заполняются без
отдельного прохода данных.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("contracts", "0022_agreement_registry_fields")]

    operations = [
        migrations.RemoveConstraint(
            model_name="program",
            name="uq_contracts_program_code",
        ),
        migrations.AddConstraint(
            model_name="program",
            constraint=models.UniqueConstraint(
                condition=models.Q(("code", ""), _negated=True),
                fields=("code", "name"), name="uq_contracts_program_code_name",
            ),
        ),
        migrations.AddConstraint(
            model_name="program",
            constraint=models.UniqueConstraint(
                condition=models.Q(("code", "")),
                fields=("name", "expense_item"), name="uq_contracts_program_uncoded",
            ),
        ),
        migrations.AddField(
            model_name="invoice",
            name="document_date",
            field=models.DateField(blank=True, null=True, verbose_name="Дата счёта"),
        ),
        migrations.AddField(
            model_name="invoice",
            name="external_id",
            field=models.CharField(blank=True, db_default="", db_index=True,
                                   default="", max_length=64,
                                   verbose_name="Идентификатор в источнике"),
        ),
        migrations.AddConstraint(
            model_name="invoice",
            constraint=models.UniqueConstraint(
                condition=models.Q(("external_id", ""), _negated=True),
                fields=("external_id",), name="uq_contracts_inv_external_id",
            ),
        ),
        migrations.AddField(
            model_name="contractpayment",
            name="document_date",
            field=models.DateField(blank=True, null=True, verbose_name="Дата счёта"),
        ),
        migrations.AddField(
            model_name="contractpayment",
            name="external_id",
            field=models.CharField(blank=True, db_default="", db_index=True,
                                   default="", max_length=64,
                                   verbose_name="Идентификатор в источнике"),
        ),
        migrations.AddConstraint(
            model_name="contractpayment",
            constraint=models.UniqueConstraint(
                condition=models.Q(("external_id", ""), _negated=True),
                fields=("external_id",), name="uq_ctr_pay_external_id",
            ),
        ),
    ]
