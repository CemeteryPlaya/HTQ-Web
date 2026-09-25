"""Читатели сводных представлений холдинга для домена работ.

Почему отдельные модели, а не обычные: у представления есть служебный
столбец ``company_slug``, которого в таблице компании нет и быть не может
(правило мультикомпанейности — в тенантных моделях поля компании нет,
изоляцию даёт схема). Обычная модель этот столбец не отдаст.

``managed = False``: таблицы под этими моделями создаёт не Django, а
``apps.companies.services.holding_views``. Миграция для них всё равно
появляется (Django записывает состояние), но DDL не выполняет.

⚠️ ``db_table`` СОВПАДАЕТ с таблицей компании — иначе и быть не может,
представление называется по таблице. Отсюда главная опасность: вызов вне
``use_holding()`` прочитал бы данные ОДНОЙ компании и выдал их за
групповые, без ошибки и без следа. Поэтому у читателей свой менеджер,
который требует контекста.

⚠️ ``base_manager_name = "objects"`` обязателен. Без него Django заводит
``Model._base_manager`` как голый ``models.Manager()`` (см.
``django.db.models.options.Options.base_manager`` — дефолт применяется,
когда ``Meta.base_manager_name`` не задан), а этим менеджером пользуются
``refresh_from_db()`` и related-дескрипторы — то есть сторож
``HoldingManager.get_queryset()`` можно было бы обойти этим путём, не трогая
``objects`` вовсе. ``Manager.raw()`` через ``get_queryset()`` не идёт ни при
каком ``base_manager_name`` — это свойство самого паттерна, а не дыра
конкретно этого сторожа.

Абстрактный ``HoldingRow`` — свой, а не импорт из ``apps/hr/holding_models``:
это межаппный импорт, он запрещён и ловится
``apps/core/tests/test_app_isolation.py``. Дублирование здесь дешевле
нарушенной границы.

Поля объявлены НЕ все, а только нужные сводке: незаявленное поле Django
просто не выбирает, а короткий список честнее показывает, что читателю
нужно. Добавлять поле сюда можно свободно — представление содержит все
столбцы модели.
"""

from __future__ import annotations

from django.db import models

from htqweb.tenancy.db import holding_active


class HoldingContextRequired(RuntimeError):
    """Читателя холдинга позвали вне ``use_holding()``."""


class HoldingManager(models.Manager):
    def get_queryset(self):
        if not holding_active():
            raise HoldingContextRequired(
                f"{self.model.__name__} читает схему holding и требует "
                f"htqweb.tenancy.db.use_holding(); вне его он прочитал бы "
                f"одну компанию и выдал её цифры за групповые"
            )
        return super().get_queryset()


class HoldingRow(models.Model):
    """Общее у всех читателей: служебный столбец, менеджер, запрет записи."""

    company_slug = models.CharField(max_length=63)

    objects = HoldingManager()

    class Meta:
        abstract = True
        managed = False
        base_manager_name = "objects"

    def save(self, *args, **kwargs):
        raise NotImplementedError("Сводка холдинга — чтение: представление не пишется")

    def delete(self, *args, **kwargs):
        raise NotImplementedError("Сводка холдинга — чтение: представление не пишется")


class HoldingProject(HoldingRow):
    name = models.CharField(max_length=200)
    status = models.CharField(max_length=20)

    class Meta(HoldingRow.Meta):
        db_table = "tasks_project"


class HoldingSite(HoldingRow):
    name = models.CharField(max_length=200)
    status = models.CharField(max_length=20)

    class Meta(HoldingRow.Meta):
        db_table = "tasks_site"


class HoldingTask(HoldingRow):
    status = models.CharField(max_length=20)
    due_date = models.DateField(null=True)
    is_deleted = models.BooleanField(default=False)

    class Meta(HoldingRow.Meta):
        db_table = "tasks_task"


class HoldingDailyReport(HoldingRow):
    work_date = models.DateField()
    is_deleted = models.BooleanField(default=False)

    class Meta(HoldingRow.Meta):
        db_table = "tasks_dailyreport"
