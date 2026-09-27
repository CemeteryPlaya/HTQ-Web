"""Журнал файловых операций — только вставка (мастер-план БЗО D-30, ТЗ §25.2).

До этой миграции ``FileEvent`` был защищён только кодом (админка без правки
и удаления). Теперь — базой, как журнал изменений модуля
(``bpp/0001_core``, триггер ``bpp_auditlog_immutable``): ``UPDATE`` и
``DELETE`` строки отвергаются триггером, чем бы их ни прислали — ORM,
сырым SQL или из консоли.

Единственное исключение — ``tenancy_bootstrap`` (``documents.assign_company``):
событиям тенантных владельцев, записанным до первой компании, он один раз
проставляет компанию. Пропускается ровно такое изменение: пустая
``company_slug`` становится непустой, а все остальные столбцы остаются
как были. Второй раз ту же строку не переписать — компания уже не пуста.

``TRUNCATE`` построчные триггеры не вызывает — тестовый раннер чистит таблицу
им, и так и должно быть.
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("files", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(
            sql=[
                """
                CREATE OR REPLACE FUNCTION files_fileevent_append_only() RETURNS trigger AS $$
                BEGIN
                    IF TG_OP = 'UPDATE'
                       AND OLD.company_slug = '' AND NEW.company_slug <> ''
                       AND (to_jsonb(NEW) - 'company_slug') = (to_jsonb(OLD) - 'company_slug')
                    THEN
                        RETURN NEW;
                    END IF;
                    RAISE EXCEPTION 'files_fileevent: журнал файловых операций только для записи';
                END;
                $$ LANGUAGE plpgsql;
                """,
                """
                CREATE TRIGGER files_fileevent_no_change
                BEFORE UPDATE OR DELETE ON files_fileevent
                FOR EACH ROW EXECUTE FUNCTION files_fileevent_append_only();
                """,
            ],
            reverse_sql=[
                "DROP TRIGGER IF EXISTS files_fileevent_no_change ON files_fileevent;",
                "DROP FUNCTION IF EXISTS files_fileevent_append_only();",
            ],
        ),
    ]
