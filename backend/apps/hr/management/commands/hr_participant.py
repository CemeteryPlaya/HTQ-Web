"""Завести системную должность «Участник (ОСУ)» в компании — блок F.

Боевой путь: холдинг заводится ``company_create`` (roadmap §7, шаг 5), после
чего этой командой в его схему кладётся орган владельцев. Демо-стенд делает
то же самое внутри ``seed_hr_demo`` тем же сервисом — двух реализаций нет.

``--company`` обязателен, умолчания на текущий ``search_path`` нет: на бою
``public`` — не компания (режим перехода, roadmap §3), и молчаливая запись
туда была бы подменой данных. Проверки те же, что у остальных команд с
``--company``: строка реестра есть, физическая схема есть (``SET search_path``
принял бы несуществующую схему молча, и запись ушла бы в ``public``).

Связь «ГД подчинён ОСУ» команда НЕ ставит — см. докстринг
``participant_service``. После команды кадровик соединяет их в дереве
оргструктуры.
"""

from django.core.management.base import BaseCommand, CommandError

from apps.hr.services import participant_service


class Command(BaseCommand):
    help = "Завести должность «Участник (ОСУ)» в схеме компании. Идемпотентно."

    def add_arguments(self, parser):
        parser.add_argument(
            "--company", dest="company", required=True,
            help="slug компании (обычно холдинг). Умолчания нет намеренно.",
        )

    def handle(self, *args, **options):
        slug = options["company"]
        from apps.companies import interface as companies

        if companies.get_company(slug) is None:
            raise CommandError(f"Компания {slug!r} не найдена в реестре.")
        if not companies.schema_exists(slug):
            raise CommandError(
                f"У компании {slug!r} нет схемы Postgres — SET search_path принял "
                f"бы её молча и данные ушли бы в public. Заведите схему: "
                f"manage.py company_create либо migrate_companies --company {slug}."
            )

        from htqweb.tenancy.db import use_company

        with use_company(slug):
            try:
                position, created = participant_service.ensure_participant()
            except participant_service.ParticipantException as exc:
                raise CommandError(exc.detail) from exc

        state = "заведена" if created else "уже есть, приведена к предписанному состоянию"
        self.stdout.write(self.style.SUCCESS(
            f"Компания {slug}: должность «{position.title}» (id={position.id}) {state}. "
            f"Соедините её с генеральным директором в дереве оргструктуры."
        ))
