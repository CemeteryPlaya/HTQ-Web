"""``Budget`` из бюджетной СТРОКИ превращается в КОНТЕЙНЕР строк.

Было: одна запись ``Budget`` = администратор × программа × год + сумма.
Стало: ``Budget`` = администратор × год × валюта (без суммы), ``BudgetLine``
= программа + сумма внутри него. Договор переезжает со ссылки на бюджет на
ссылку на строку — деньги выделены программе и списываются с неё.

Порядок здесь важен и потому расписан вручную, а не собран
``makemigrations``:

1. старая таблица ПЕРЕИМЕНОВЫВАЕТСЯ в ``BudgetLine`` (``RenameModel``), а не
   пересоздаётся — так сохраняются id строк и, главное, ссылки договоров на
   них: ``Agreement.budget_id`` продолжает указывать туда же, куда указывал,
   и переименовывается в ``budget_line_id`` вместе с колонкой;
2. рядом создаётся НОВЫЙ пустой ``Budget`` — контейнер;
3. данные группируются: на каждую связку «администратор × год × валюта»
   заводится контейнер, строки к нему привязываются;
4. только после этого у строки убираются колонки, переехавшие в контейнер.

Обратная миграция не пишется намеренно: разложить контейнер обратно в
плоские строки означало бы решить, что делать с бюджетами, у которых строк
несколько, а согласование одно на всех — восстановить прежнее состояние
из нового нельзя. Откат — из бэкапа.
"""

import django.db.models.deletion
import django.db.models.functions.datetime
from django.db import migrations, models


def group_lines_into_budgets(apps, schema_editor):
    """Собрать контейнеры из уже существующих плоских строк.

    Ключ группировки — тот же, что стал ключом уникальности контейнера:
    администратор × год × валюта.

    Состояние согласования контейнера выводится по правилу «согласован,
    только если согласованы ВСЕ его строки». Обратное правило («хоть
    одна») пометило бы бюджет согласованным при том, что часть его сумм
    никто не утверждал, — а с этого момента с них можно тратить. Группа со
    смешанными состояниями поэтому становится черновиком: её придётся
    отправить на согласование заново, целиком, что и есть новая семантика.
    """
    Budget = apps.get_model("contracts", "Budget")
    BudgetLine = apps.get_model("contracts", "BudgetLine")
    ApprovalProcess = apps.get_model("signoff", "ApprovalProcess")

    groups: dict[tuple[int, int, str], list] = {}
    for line in BudgetLine.objects.all().order_by("pk"):
        groups.setdefault(
            (line.administrator_id, line.period_year, line.currency), []).append(line)

    for (administrator_id, period_year, currency), lines in groups.items():
        approved = all(line.approval_state == "approved" for line in lines)
        # Закрытым контейнер становится, только если закрыты все строки:
        # закрытие — это «бюджет отработан», и одна живая строка означает,
        # что он ещё нет.
        closed = all(line.status == "closed" for line in lines)
        # Примечания строк не склеиваются: у строки своё поле `note`, оно
        # никуда не делось, и дублировать его в контейнере нечего.
        budget = Budget.objects.create(
            administrator_id=administrator_id,
            period_year=period_year,
            currency=currency,
            status="closed" if closed else "active",
            note="",
            approval_state="approved" if approved else "draft",
        )
        BudgetLine.objects.filter(pk__in=[line.pk for line in lines]).update(
            budget_id=budget.pk)

        # Процессы согласования адресуют бюджет парой (subject_type,
        # subject_id) — без FK, поэтому переехавший id починить некому,
        # кроме нас. Процесс над любой строкой группы теперь относится к её
        # контейнеру.
        ApprovalProcess.objects.filter(
            subject_type="contracts.budget",
            subject_id__in=[line.pk for line in lines],
        ).update(subject_id=budget.pk)


class Migration(migrations.Migration):

    dependencies = [
        ("contracts", "0004_counterparty_vat_boolean"),
        # ApprovalProcess переписывается в data-миграции: её таблица обязана
        # существовать к этому моменту.
        ("signoff", "0001_initial"),
    ]

    operations = [
        # ── 1. Старый Budget → BudgetLine, ссылка договора вместе с ним ──
        migrations.RemoveConstraint(
            model_name="budget",
            name="uq_contracts_budget_admin_program_year",
        ),
        migrations.RemoveIndex(model_name="agreement",
                               name="ix_contracts_agr_budget_st"),
        migrations.RenameModel(old_name="Budget", new_name="BudgetLine"),
        migrations.RenameField(
            model_name="agreement", old_name="budget", new_name="budget_line",
        ),
        migrations.AlterField(
            model_name="agreement",
            name="budget_line",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="agreements", to="contracts.budgetline",
            ),
        ),

        # ── 2. Новый Budget — контейнер ──────────────────────────────────
        migrations.CreateModel(
            name="Budget",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True,
                                        serialize=False, verbose_name="ID")),
                ("approval_state", models.CharField(
                    choices=[("draft", "Черновик"), ("pending", "На согласовании"),
                             ("approved", "Согласовано"), ("rejected", "Отклонено")],
                    db_default="draft", db_index=True, default="draft",
                    max_length=16, verbose_name="Состояние согласования")),
                ("period_year", models.IntegerField()),
                ("currency", models.CharField(db_default="KZT", default="KZT",
                                              max_length=3)),
                ("status", models.CharField(
                    choices=[("active", "Активен"), ("closed", "Закрыт")],
                    db_default="active", default="active", max_length=16)),
                ("note", models.TextField(blank=True, db_default="", default="")),
                ("created_at", models.DateTimeField(
                    auto_now_add=True,
                    db_default=django.db.models.functions.datetime.Now())),
                ("updated_at", models.DateTimeField(
                    auto_now=True,
                    db_default=django.db.models.functions.datetime.Now())),
                ("administrator", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="budgets", to="contracts.administrator")),
            ],
            options={
                "verbose_name": "Бюджет",
                "verbose_name_plural": "Бюджеты",
                "ordering": ("-period_year", "administrator_id"),
            },
        ),
        migrations.AddConstraint(
            model_name="budget",
            constraint=models.UniqueConstraint(
                fields=("administrator", "period_year", "currency"),
                name="uq_contracts_budget_admin_year_currency"),
        ),

        # ── 3. Привязка строк к контейнерам ──────────────────────────────
        # Сначала nullable: заполнять её будет data-миграция, а до неё
        # значения взяться неоткуда.
        migrations.AddField(
            model_name="budgetline",
            name="budget",
            field=models.ForeignKey(
                null=True, on_delete=django.db.models.deletion.CASCADE,
                related_name="lines", to="contracts.budget"),
        ),
        migrations.RunPython(group_lines_into_budgets,
                             migrations.RunPython.noop),
        migrations.AlterField(
            model_name="budgetline",
            name="budget",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="lines", to="contracts.budget"),
        ),

        # ── 4. Колонки, переехавшие в контейнер, со строки убираются ─────
        migrations.RemoveField(model_name="budgetline", name="administrator"),
        migrations.RemoveField(model_name="budgetline", name="period_year"),
        migrations.RemoveField(model_name="budgetline", name="currency"),
        migrations.RemoveField(model_name="budgetline", name="status"),
        migrations.RemoveField(model_name="budgetline", name="approval_state"),
        migrations.AlterField(
            model_name="budgetline",
            name="program",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="budget_lines", to="contracts.program"),
        ),
        migrations.AlterModelOptions(
            name="budgetline",
            options={"ordering": ("budget_id", "program_id"),
                     "verbose_name": "Строка бюджета",
                     "verbose_name_plural": "Строки бюджета"},
        ),
        migrations.AddConstraint(
            model_name="budgetline",
            constraint=models.UniqueConstraint(
                fields=("budget", "program"),
                name="uq_contracts_budgetline_budget_program"),
        ),
        migrations.AddIndex(
            model_name="agreement",
            index=models.Index(fields=["budget_line", "status"],
                               name="ix_contracts_agr_line_st"),
        ),
    ]
