"""Читатели сводных представлений холдинга для модуля БЗО (A8.1).

Устройство и опасности — как в ``apps/tasks/holding_models.py`` (у представления
есть служебный ``company_slug``; ``db_table`` совпадает с таблицей компании,
поэтому вызов вне ``use_holding()`` прочитал бы ОДНУ компанию и выдал её за
группу — менеджер такой вызов запрещает). Абстрактный ``HoldingRow`` свой:
межаппный импорт запрещён ``test_app_isolation``.
"""

from __future__ import annotations

import uuid

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
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
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


class HoldingBudget(HoldingRow):
    status = models.CharField(max_length=16)
    currency_code = models.CharField(max_length=3)
    active_version_id = models.UUIDField(null=True)

    class Meta(HoldingRow.Meta):
        db_table = "bpp_budget"


class HoldingBudgetVersion(HoldingRow):
    budget_id = models.UUIDField()
    state = models.CharField(max_length=16)

    class Meta(HoldingRow.Meta):
        db_table = "bpp_budgetversion"


class HoldingBudgetLine(HoldingRow):
    version_id = models.UUIDField()
    limit_amount = models.DecimalField(max_digits=18, decimal_places=2)

    class Meta(HoldingRow.Meta):
        db_table = "bpp_budgetline"


class HoldingInvoice(HoldingRow):
    status = models.CharField(max_length=16)
    amount_kzt = models.DecimalField(max_digits=18, decimal_places=2, null=True)

    class Meta(HoldingRow.Meta):
        db_table = "bpp_invoice"


class HoldingAgreement(HoldingRow):
    status = models.CharField(max_length=16)

    class Meta(HoldingRow.Meta):
        db_table = "bpp_agreement"
