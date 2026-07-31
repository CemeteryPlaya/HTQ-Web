"""«НДС» у контрагента: свободный текст → булев признак «с НДС / без НДС».

Поле заводилось строкой, пока не было известно, что заказчик за ним имеет
в виду (ставку? номер свидетельства? признак плательщика?). Ответ —
признак, поэтому колонка становится ``BooleanField``.

Прямым ``ALTER TYPE`` это не делается: Postgres не приводит ``varchar`` к
``boolean`` автоматически и уронил бы миграцию. Поэтому классические четыре
шага — новая колонка, перенос значений, удаление старой, переименование.

**Перенос значений — эвристика, и это осознанно.** В колонке лежит текст,
который вводили руками, и однозначного отображения в булево у него нет.
Правило: пусто или явное отрицание («нет», «без НДС», «—», «0») →
``False``; любой другой непустой текст → ``True``, потому что человек,
вписавший туда что-то осмысленное, отмечал плательщика. Спорные строки
после раскатки проверяются глазами по списку контрагентов — их единицы, а
альтернатива (обнулить всё в ``False``) молча потеряла бы больше.

Откат восстанавливает текст, но НЕ исходные формулировки: ``True``
превращается в «плательщик НДС», ``False`` — в пустую строку. Вернуть
ровно то, что было введено, невозможно — это и есть цена перехода.
"""

from django.db import migrations, models

# Что считается «без НДС». Сравнение по нижнему регистру и без пробелов по
# краям; всё остальное непустое — плательщик.
NEGATIVE = {
    "", "-", "--", "—", "0", "нет", "не", "без ндс", "без", "не плательщик",
    "не плательщик ндс", "no", "none", "false", "н/д", "n/a", "отсутствует",
}


def text_to_flag(apps, schema_editor):
    Counterparty = apps.get_model("contracts", "Counterparty")
    for row in Counterparty.objects.all().iterator():
        raw = (row.vat or "").strip().lower()
        row.vat_flag = raw not in NEGATIVE
        row.save(update_fields=["vat_flag"])


def flag_to_text(apps, schema_editor):
    Counterparty = apps.get_model("contracts", "Counterparty")
    Counterparty.objects.filter(vat_flag=True).update(vat="плательщик НДС")
    Counterparty.objects.filter(vat_flag=False).update(vat="")


class Migration(migrations.Migration):

    dependencies = [
        ("contracts", "0003_drop_administrator_full_name"),
    ]

    operations = [
        # Определение здесь ФИНАЛЬНОЕ (вместе с verbose_name): после
        # переименования оно и станет состоянием поля `vat`, и расхождения
        # с моделью не будет.
        migrations.AddField(
            model_name="counterparty",
            name="vat_flag",
            field=models.BooleanField(default=False, db_default=False,
                                      verbose_name="Плательщик НДС"),
        ),
        migrations.RunPython(text_to_flag, flag_to_text),
        migrations.RemoveField(model_name="counterparty", name="vat"),
        migrations.RenameField(
            model_name="counterparty", old_name="vat_flag", new_name="vat",
        ),
    ]
