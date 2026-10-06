"""«Проект» модуля БЗО (D-02) — сущность, на которую ссылаются бюджет,
документы и ``tasks.Project`` (``project_ref``).

Заказчик — голая ссылка на контрагента модуля ``bpp`` плюс подпись
(межаппный FK запрещён). Страна — атрибут проекта: бюджет ведётся в стране
проекта (Q-B08).
"""

from __future__ import annotations

import uuid

from django.db import models
from django.db.models.functions import Lower, Now


class ProjectKind(models.TextChoices):
    PROJECT = "project", "Проект"
    COMPANY_OVERHEAD = "company_overhead", "Общие расходы компании"


class ProjectStatus(models.TextChoices):
    ACTIVE = "active", "Активен"
    CLOSED = "closed", "Закрыт"
    ARCHIVED = "archived", "Архив"


class Project(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=255)
    kind = models.CharField(max_length=24, choices=ProjectKind.choices,
                            default=ProjectKind.PROJECT, db_default=ProjectKind.PROJECT.value)
    status = models.CharField(max_length=16, choices=ProjectStatus.choices,
                              default=ProjectStatus.ACTIVE, db_default=ProjectStatus.ACTIVE.value)
    country_code = models.CharField(max_length=2)
    manager_user_id = models.IntegerField(null=True, blank=True)
    customer_name = models.CharField(max_length=255, default="", blank=True)
    customer_counterparty_id = models.CharField(max_length=64, default="", blank=True)
    date_start = models.DateField(null=True, blank=True)
    date_end = models.DateField(null=True, blank=True)
    ext_1c_ref = models.CharField(max_length=64, default="", blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())
    created_by = models.IntegerField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True, db_default=Now())

    class Meta:
        ordering = ("code",)
        constraints = [
            # Ключ записи в 1С уникален среди непустых внутри компании (A7.3, D-S7-5).
            models.UniqueConstraint(fields=["ext_1c_ref"], condition=~models.Q(ext_1c_ref=""),
                                    name="uq_project_ext_1c"),
            # Только нижний регистр (D-S8-4): уникальность выше регистрозависима,
            # и GUID, введённый мимо сервиса (django-admin, ORM) заглавными,
            # обошёл бы её. Форма django-admin получает ошибку формы.
            models.CheckConstraint(condition=models.Q(ext_1c_ref=Lower("ext_1c_ref")),
                                   name="ck_project_ext_1c_lower",
                                   violation_error_message="«Код в 1С» хранится в нижнем "
                                                           "регистре (GUID строчными буквами)."),
        ]
        verbose_name = "Проект"
        verbose_name_plural = "Проекты"


class ProjectMember(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="members")
    user_id = models.IntegerField()
    added_by = models.IntegerField(null=True, blank=True)
    added_at = models.DateTimeField(auto_now_add=True, db_default=Now())

    class Meta:
        constraints = [models.UniqueConstraint(fields=["project", "user_id"],
                                               name="uq_project_member")]
        verbose_name = "Участник проекта"
        verbose_name_plural = "Участники проекта"


# ── Проектная структура (спек docs/plans/2026-10-06-project-structure-spec.md) ──
#
# Своя у каждого проекта и НЕ связана с кадровой схемой ``hr`` (должности,
# уровни N-1…N-4): человек на проекте может занимать роль, не совпадающую с
# его кадровой должностью. Сотрудник — ``hr.Employee.id`` голым числом
# (межаппный FK запрещён), данные о нём — через ``hr.interface``.


class ProjectPart(models.TextChoices):
    OFFICE = "office", "Офис"
    SITE = "site", "Объект"


class ProjectRole(models.Model):
    """Справочник проектных ролей компании: «Технический директор» — одна и та
    же роль на всех проектах (на неё опираются маршруты согласования и учёт,
    подпроекты 2 и 3). Уровни L1–L4 — своя шкала проекта."""

    name = models.CharField(max_length=100, unique=True)
    level = models.PositiveSmallIntegerField()
    # Подставляется в новое место; часть хранится у места (PS-7): «Специалист»
    # бывает и в офисе, и на объекте.
    default_part = models.CharField(max_length=8, choices=ProjectPart.choices,
                                    default=ProjectPart.OFFICE,
                                    db_default=ProjectPart.OFFICE.value)
    sort_order = models.IntegerField(default=0, db_default=0)
    is_active = models.BooleanField(default=True, db_default=True)
    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())
    updated_at = models.DateTimeField(auto_now=True, db_default=Now())

    class Meta:
        ordering = ("level", "sort_order", "name")
        constraints = [models.CheckConstraint(condition=models.Q(level__gte=1, level__lte=4),
                                              name="ck_project_role_level")]
        verbose_name = "Проектная роль"
        verbose_name_plural = "Проектные роли"

    def __str__(self) -> str:
        return f"L{self.level} {self.name}"


class ProjectSlot(models.Model):
    """Место в структуре проекта: роль, руководитель-место и план людей.

    Места не удаляются, а закрываются датой (``closed_on`` — закрыто С этой
    даты): история нужна учёту, а подчинённые переживают смену людей.
    ``parent`` — ``RESTRICT``, а не ``PROTECT``: удаление проекта каскадом
    сносит и руководителя, и подчинённого одним проходом, ``PROTECT`` его
    уронил бы."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="slots")
    role = models.ForeignKey(ProjectRole, on_delete=models.PROTECT, related_name="slots")
    part = models.CharField(max_length=8, choices=ProjectPart.choices)
    title = models.CharField(max_length=255, default="", blank=True)
    parent = models.ForeignKey("self", on_delete=models.RESTRICT, null=True, blank=True,
                               related_name="children")
    planned_headcount = models.PositiveSmallIntegerField(default=1, db_default=1)
    closed_on = models.DateField(null=True, blank=True)
    created_by = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())
    updated_at = models.DateTimeField(auto_now=True, db_default=Now())

    class Meta:
        constraints = [models.CheckConstraint(condition=models.Q(planned_headcount__gte=1),
                                              name="ck_project_slot_planned")]
        verbose_name = "Место в структуре проекта"
        verbose_name_plural = "Места в структуре проекта"


class ProjectAssignment(models.Model):
    """Сотрудник на месте с даты по дату (обе включительно, ``date_to`` пусто —
    бессрочно). Начавшееся назначение не удаляется, а закрывается датой."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    slot = models.ForeignKey(ProjectSlot, on_delete=models.CASCADE, related_name="assignments")
    employee_id = models.IntegerField(db_index=True)
    date_from = models.DateField()
    date_to = models.DateField(null=True, blank=True)
    created_by = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())
    updated_at = models.DateTimeField(auto_now=True, db_default=Now())

    class Meta:
        constraints = [models.CheckConstraint(
            condition=models.Q(date_to__isnull=True) | models.Q(date_to__gte=models.F("date_from")),
            name="ck_project_assignment_dates")]
        verbose_name = "Назначение на проекте"
        verbose_name_plural = "Назначения на проекте"
