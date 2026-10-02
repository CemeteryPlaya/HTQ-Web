"""«Проект» модуля БЗО (D-02) — сущность, на которую ссылаются бюджет,
документы и ``tasks.Project`` (``project_ref``).

Заказчик — голая ссылка на контрагента модуля ``bpp`` плюс подпись
(межаппный FK запрещён). Страна — атрибут проекта: бюджет ведётся в стране
проекта (Q-B08).
"""

from __future__ import annotations

import uuid

from django.db import models
from django.db.models.functions import Now


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
