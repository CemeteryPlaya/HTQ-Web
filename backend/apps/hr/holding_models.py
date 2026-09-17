"""Читатели сводных представлений холдинга для домена кадров.

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

    def save(self, *args, **kwargs):
        raise NotImplementedError("Сводка холдинга — чтение: представление не пишется")

    def delete(self, *args, **kwargs):
        raise NotImplementedError("Сводка холдинга — чтение: представление не пишется")


class HoldingEmployee(HoldingRow):
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    status = models.CharField(max_length=20)
    is_deleted = models.BooleanField(default=False)
    department_id = models.IntegerField(null=True)
    position_id = models.IntegerField(null=True)

    class Meta(HoldingRow.Meta):
        db_table = "hr_employee"


class HoldingDepartment(HoldingRow):
    name = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)

    class Meta(HoldingRow.Meta):
        db_table = "hr_department"


class HoldingPosition(HoldingRow):
    title = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)
    level = models.IntegerField(default=2)

    class Meta(HoldingRow.Meta):
        db_table = "hr_position"


class HoldingStaffingPosition(HoldingRow):
    headcount = models.DecimalField(max_digits=5, decimal_places=2)
    salary = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta(HoldingRow.Meta):
        db_table = "hr_staffingposition"
