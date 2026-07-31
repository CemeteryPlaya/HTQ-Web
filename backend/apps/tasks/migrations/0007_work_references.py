"""Три справочника, на которых стоит планирование работ по объекту.

``EquipmentCategory`` и ``WorkRole`` нужны, чтобы потребность в ресурсе можно
было выразить количеством («2 кары», «2 монтажника»), а не только именем
конкретной машины или человека. ``WorkVolumeType`` — чтобы «250 валов» стало
числом с единицей измерения, а не строкой в названии задачи.

Строк не сеет: содержимое этих справочников зависит от парка и от вида работ
конкретной организации, а угадывать его — значит навязывать всем чужой
словарь. Категории техники наполняет следующая миграция, из уже накопленного
текста в ``Equipment.category``.
"""

from django.db import migrations, models
from django.db.models.functions import Now


class Migration(migrations.Migration):

    dependencies = [("tasks", "0006_engagement_nulls_not_distinct")]

    operations = [
        migrations.CreateModel(
            name="EquipmentCategory",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True,
                                        serialize=False, verbose_name="ID")),
                ("slug", models.CharField(max_length=50, unique=True)),
                ("name", models.CharField(max_length=100, unique=True)),
                ("is_active", models.BooleanField(db_default=True, db_index=True,
                                                  default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True,
                                                    db_default=Now())),
                ("updated_at", models.DateTimeField(auto_now=True,
                                                    db_default=Now())),
            ],
        ),
        migrations.CreateModel(
            name="WorkRole",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True,
                                        serialize=False, verbose_name="ID")),
                ("slug", models.CharField(max_length=50, unique=True)),
                ("name", models.CharField(max_length=100, unique=True)),
                ("is_active", models.BooleanField(db_default=True, db_index=True,
                                                  default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True,
                                                    db_default=Now())),
                ("updated_at", models.DateTimeField(auto_now=True,
                                                    db_default=Now())),
            ],
        ),
        migrations.CreateModel(
            name="WorkVolumeType",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True,
                                        serialize=False, verbose_name="ID")),
                ("slug", models.CharField(max_length=50, unique=True)),
                ("name", models.CharField(max_length=100, unique=True)),
                ("unit", models.CharField(
                    choices=[("piece", "шт"), ("meter", "м"),
                             ("sq_meter", "м²"), ("ton", "т")],
                    db_default="piece", default="piece", max_length=20)),
                ("is_active", models.BooleanField(db_default=True, db_index=True,
                                                  default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True,
                                                    db_default=Now())),
                ("updated_at", models.DateTimeField(auto_now=True,
                                                    db_default=Now())),
            ],
        ),
    ]
