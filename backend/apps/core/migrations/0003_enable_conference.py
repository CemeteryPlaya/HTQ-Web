from django.db import migrations


def enable_conference(apps, schema_editor):
    """Включить `conference` в реестре сервисов.

    Миграция 0001 засеяла его выключенным: SFU/webtransport-стек был отложен
    «до прода» и физически не поднимался. Стек поднят (docker-compose: sfu +
    webtransport больше не под профилем production, сигналинг требует
    платформенный JWT), поэтому дефолт меняется на «включён» — и для новых
    установок, и для уже развёрнутых баз, где строка осталась с enabled=False.
    """
    ServiceStatus = apps.get_model("core", "ServiceStatus")
    ServiceStatus.objects.update_or_create(
        app_label="conference",
        defaults={"enabled": True},
    )


def disable_conference(apps, schema_editor):
    ServiceStatus = apps.get_model("core", "ServiceStatus")
    ServiceStatus.objects.filter(app_label="conference").update(enabled=False)


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0002_alter_servicestatus_options'),
    ]

    operations = [
        migrations.RunPython(enable_conference, disable_conference),
    ]
