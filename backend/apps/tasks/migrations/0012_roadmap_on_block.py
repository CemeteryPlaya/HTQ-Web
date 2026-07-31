"""Роудмап переезжает с площадки на блок.

Решение заказчика от 30.07.2026: иерархия работ пятиуровневая —
Проект → Площадка → **Блок** → Роудмап → Задача. До этой миграции роудмап
висел на площадке, а блок был боковым измерением, указываемым только на
задаче.

Площадка отдельной колонкой на роудмапе больше НЕ хранится: она выводится
джойном ``site_block__site``. Оставить обе значило бы завести второй источник
правды, расходящийся при первом же переносе блока.

Про бэкфилл: фича не выкатывалась, и данные тут в худшем случае
девелоперские — но молча терять роудмапы миграция всё равно не должна.
Каждому берётся первый блок его площадки по ``order``; если блоков нет,
заводится «Блок 1». Придуманный блок лучше упавшей миграции: имя очевидно
временное, и его переименуют, а не будут гадать, куда делся пакет работ.

**Почему два ``RunPython``, а не один с прямым и обратным ходом.** Реверс
``RemoveField`` возвращает колонку ровно такой, какой она была, — то есть
``NOT NULL``, и на непустой таблице это падает. Поэтому перед удалением
площадка сначала делается nullable, а обратное заполнение вынесено в
отдельную операцию, стоящую МЕЖДУ этим ослаблением и удалением: при откате
она отработает после того, как колонка вернётся, и до того, как на неё
снова наложат ``NOT NULL``. Один совмещённый ``RunPython`` встал бы не в то
место цепочки.
"""

from django.db import migrations, models
import django.db.models.deletion


def noop(apps, schema_editor):
    """Заглушка: у соответствующей операции содержателен только один ход."""


def fill_blocks(apps, schema_editor):
    Roadmap = apps.get_model("tasks", "Roadmap")
    SiteBlock = apps.get_model("tasks", "SiteBlock")

    # Один проход по блокам вместо запроса на каждый роудмап: площадок и
    # блоков десятки, роудмапов могут быть сотни.
    first_block: dict[int, int] = {}
    for block_id, site_id in (SiteBlock.objects.order_by("site_id", "order", "id")
                              .values_list("id", "site_id")):
        first_block.setdefault(site_id, block_id)

    invented = False
    for roadmap_id, site_id in Roadmap.objects.values_list("id", "site_id"):
        block_id = first_block.get(site_id)
        if block_id is None:
            block_id = SiteBlock.objects.create(
                site_id=site_id, name="Блок 1", order=1, status="planned",
            ).id
            first_block[site_id] = block_id
            invented = True
        Roadmap.objects.filter(id=roadmap_id).update(site_block_id=block_id)

    if invented:
        # Обязательно, и не «на всякий случай». Миграция идёт одной
        # транзакцией, а следующая операция — ALTER TABLE, накладывающий
        # NOT NULL. Postgres отказывается менять таблицу, у которой в этой
        # же транзакции остались НЕОТРАБОТАННЫЕ отложенные триггеры FK, а
        # INSERT-ы блоков выше ровно их и создают:
        #   cannot ALTER TABLE "tasks_siteblock" because it has pending
        #   trigger events
        # ``SET CONSTRAINTS ALL IMMEDIATE`` заставляет их сработать прямо
        # сейчас. Ветка с уже существующими блоками ничего не вставляет и
        # до этой строки не доходит — потому баг и не проявлялся, пока не
        # завели тест на площадку без блоков.
        schema_editor.execute("SET CONSTRAINTS ALL IMMEDIATE")


def fill_sites(apps, schema_editor):
    """Откат: площадка восстанавливается из блока — из того же, откуда бралась."""
    Roadmap = apps.get_model("tasks", "Roadmap")
    for roadmap_id, site_id in (Roadmap.objects
                                .values_list("id", "site_block__site_id")):
        Roadmap.objects.filter(id=roadmap_id).update(site_id=site_id)


class Migration(migrations.Migration):

    dependencies = [("tasks", "0011_resource_allocation")]

    operations = [
        migrations.RemoveConstraint(model_name="roadmap",
                                    name="uq_roadmap_name"),
        migrations.AddField(
            model_name="roadmap", name="site_block",
            field=models.ForeignKey(
                null=True, on_delete=django.db.models.deletion.PROTECT,
                related_name="roadmaps", to="tasks.siteblock"),
        ),
        migrations.RunPython(fill_blocks, noop),
        migrations.AlterField(
            model_name="roadmap", name="site_block",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="roadmaps", to="tasks.siteblock"),
        ),
        # Ослабление перед удалением — ради обратимости, см. докстринг.
        migrations.AlterField(
            model_name="roadmap", name="site",
            field=models.ForeignKey(
                null=True, on_delete=django.db.models.deletion.PROTECT,
                related_name="roadmaps", to="tasks.site"),
        ),
        migrations.RunPython(noop, fill_sites),
        migrations.RemoveField(model_name="roadmap", name="site"),
        migrations.AddConstraint(
            model_name="roadmap",
            constraint=models.UniqueConstraint(
                fields=("project", "site_block", "name"),
                name="uq_roadmap_name"),
        ),
    ]
